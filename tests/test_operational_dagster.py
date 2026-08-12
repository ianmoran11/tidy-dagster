from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from dagster import DagsterInstance, DagsterRunStatus, RunsFilter
from dagster._core.storage.tags import RUN_KEY_TAG, SENSOR_NAME_TAG

from tidy_orchestrator.dagster_defs import WORK_UNIT_PARTITIONS
from tidy_orchestrator.work_units import discover_work_units, work_unit_run_key

PROJECT = Path(__file__).parents[1]
SENSOR_NAME = "provider_free_work_unit_sensor"


@pytest.mark.operational
@pytest.mark.timeout(180)
@pytest.mark.skipif(
    os.environ.get("RUN_DAGSTER_OPERATIONAL") != "1",
    reason="set RUN_DAGSTER_OPERATIONAL=1 for real dg dev webserver/daemon smoke",
)
def test_real_daemon_sensor_tick_launch_dedup_and_restart(tmp_path: Path) -> None:
    home = tmp_path / "dagster-home"
    home.mkdir()
    shutil.copy(PROJECT / ".dagster/dagster.yaml.example", home / "dagster.yaml")
    repository = tmp_path / "repository"
    port = _free_port()
    environment = {
        **os.environ,
        "DAGSTER_HOME": str(home),
        "TIDY_PROJECT_ROOT": str(PROJECT),
        "TIDY_ARTIFACT_ROOT": str(repository),
    }
    log = tmp_path / "dg-dev.log"
    catalog = discover_work_units(PROJECT)
    expected_keys = {unit.work_unit_id for unit in catalog.units}

    process = _start(environment, port, log)
    try:
        _wait_healthy(process, port, log)
        with DagsterInstance.from_config(str(home)) as instance:
            deadline = time.monotonic() + 120
            runs = []
            while time.monotonic() < deadline:
                runs = instance.get_runs(
                    RunsFilter(tags={SENSOR_NAME_TAG: SENSOR_NAME})
                )
                if len(runs) == 3 and all(
                    run.status == DagsterRunStatus.SUCCESS for run in runs
                ):
                    break
                if process.poll() is not None:
                    pytest.fail(f"dg dev exited early:\n{log.read_text()}")
                time.sleep(0.5)
            else:
                run_statuses = [(run.run_id, run.status) for run in runs]
                pytest.fail(
                    "default sensor did not launch three successful jobs; "
                    f"runs={run_statuses}\n{log.read_text()}"
                )
            assert (
                set(instance.get_dynamic_partitions(WORK_UNIT_PARTITIONS.name))
                == expected_keys
            )
            assert {run.tags[RUN_KEY_TAG] for run in runs} == {
                work_unit_run_key(unit) for unit in catalog.units
            }
            for run in runs:
                materialized_assets = {
                    record.event_log_entry.dagster_event.asset_key.to_user_string()
                    for record in instance.get_records_for_run(run.run_id).records
                    if record.event_log_entry.dagster_event is not None
                    and record.event_log_entry.dagster_event.asset_key is not None
                    and record.event_log_entry.dagster_event.is_step_materialization
                }
                assert "source_catalog_snapshot" in materialized_assets
                assert "active_work_unit_projection" in materialized_assets
            states = [
                state
                for state in instance.all_instigator_state()
                if state.name == SENSOR_NAME
            ]
            assert len(states) == 1
            state = states[0]
            assert state.instigator_data.cursor == catalog.catalog_digest
            tick_deadline = time.monotonic() + 30
            ticks = []
            while time.monotonic() < tick_deadline:
                ticks = instance.get_ticks(
                    state.instigator_origin_id, state.selector_id, limit=1000
                )
                if any(str(tick.status.value).upper() == "SUCCESS" for tick in ticks):
                    break
                if process.poll() is not None:
                    pytest.fail(
                        f"dg dev exited before tick completion:\n{log.read_text()}"
                    )
                time.sleep(0.25)
            assert any(str(tick.status.value).upper() == "SUCCESS" for tick in ticks)
    finally:
        _stop(process)

    first_output = log.read_text()
    assert "daemon" in first_output.lower()
    process = _start(environment, port, log)
    try:
        _wait_healthy(process, port, log)
        time.sleep(4)
        with DagsterInstance.from_config(str(home)) as instance:
            runs_after_restart = instance.get_runs(
                RunsFilter(tags={SENSOR_NAME_TAG: SENSOR_NAME})
            )
            assert len(runs_after_restart) == 3
            assert all(
                run.status == DagsterRunStatus.SUCCESS for run in runs_after_restart
            )
            states = [
                state
                for state in instance.all_instigator_state()
                if state.name == SENSOR_NAME
            ]
            assert len(states) == 1
            assert states[0].instigator_data.cursor == catalog.catalog_digest
    finally:
        _stop(process)
    assert process.poll() is not None
    assert home.joinpath("history").exists()


def _start(environment: dict[str, str], port: int, log: Path) -> subprocess.Popen:
    handle = log.open("ab", buffering=0)
    process = subprocess.Popen(
        [
            "uv",
            "run",
            "dg",
            "dev",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=PROJECT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    handle.close()
    return process


def _wait_healthy(process: subprocess.Popen, port: int, log: Path) -> None:
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"dg dev exited before health:\n{log.read_text()}")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=1
            ) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.25)
    pytest.fail(f"dg dev did not become healthy:\n{log.read_text()}")


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])
