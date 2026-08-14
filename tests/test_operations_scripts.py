from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import signal
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

PROJECT = Path(__file__).parents[1]


def _load(name: str, path: Path) -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


def test_tidy_prototype_cli_is_directly_executable() -> None:
    script = PROJECT / "scripts/tidy-prototype"
    completed = subprocess.run(
        [str(script), "--help"], cwd=PROJECT, capture_output=True, text=True
    )
    assert completed.returncode == 0
    assert "run the exact product cohort" in completed.stdout


def test_tidy_prototype_cli_completes_the_five_workbook_replay(
    tmp_path: Path,
) -> None:
    script = PROJECT / "scripts/tidy-prototype"
    completed = subprocess.run(
        [
            str(script),
            "run",
            "--cohort",
            "fixtures/product-prototype/prisoners-table-30-2021-2025.json",
            "--mode",
            "replay",
            "--output",
            str(tmp_path / "prototype-run"),
            "--recorded-at",
            "2026-08-13T12:00:00+00:00",
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["acceptedWorkbookCount"] == 5
    assert result["exceptionWorkbookCount"] == 0
    assert result["canonicalObservationCount"] == 1215
    assert result["providerCalls"] == 0
    assert (tmp_path / "prototype-run" / "collation-report.json").is_file()


def test_dagster_ui_status_is_safe_and_does_not_touch_tailscale() -> None:
    script = PROJECT / "scripts/dagster-ui"
    source = script.read_text()
    assert '["tailscale"' not in source
    assert "/usr/local/bin/tailscale" not in source
    completed = subprocess.run(
        [str(script), "status"], cwd=PROJECT, capture_output=True, text=True
    )
    assert completed.returncode in {0, 1}
    assert "loopback_listener=" in completed.stdout


def test_ui_uses_repo_persistent_tmpdir(monkeypatch, tmp_path) -> None:
    module = _load("dagster_ui_tmpdir", PROJECT / "scripts/dagster-ui")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("TMPDIR", "/ephemeral/tool-owned-directory")
    environment = module.minimal_environment()
    assert environment["TMPDIR"] == str(tmp_path / ".dagster" / "tmp")
    assert Path(environment["TMPDIR"]).is_dir()


def test_ui_refuses_stale_pid_reuse_with_unrelated_live_group(monkeypatch) -> None:
    module = _load("dagster_ui_stale", PROJECT / "scripts/dagster-ui")
    ownership = module.Ownership(41, 41, "token", "start", "exact", "digest")
    monkeypatch.setattr(module, "read_ownership", lambda: ownership)
    monkeypatch.setattr(module, "valid_owned_leader", lambda _value: False)
    monkeypatch.setattr(module, "group_exists", lambda _pgid: True)
    called = []
    monkeypatch.setattr(module.os, "killpg", lambda *args: called.append(args))
    assert module.stop() == 1
    assert called == []


def test_ui_stops_token_verified_children_after_leader_exits(
    monkeypatch, tmp_path
) -> None:
    module = _load("dagster_ui_child_only", PROJECT / "scripts/dagster-ui")
    ownership = module.Ownership(40, 40, "token", "start", "exact", "digest")
    monkeypatch.setattr(module, "PID_FILE", tmp_path / "ownership.json")
    module.PID_FILE.write_text("owned")
    monkeypatch.setattr(module, "read_ownership", lambda: ownership)
    monkeypatch.setattr(module, "valid_owned_leader", lambda _value: False)
    monkeypatch.setattr(module, "process_row", lambda _pid: None)
    monkeypatch.setattr(module, "group_exists", lambda _pgid: True)
    monkeypatch.setattr(module, "valid_owned_group", lambda _value: True)
    stopped = []
    monkeypatch.setattr(
        module, "terminate_owned_group", lambda value: stopped.append(value) or True
    )
    assert module.stop() == 0
    assert stopped == [ownership]
    assert not module.PID_FILE.exists()


def test_ui_kills_surviving_owned_leader_and_children(monkeypatch) -> None:
    module = _load("dagster_ui_survivors", PROJECT / "scripts/dagster-ui")
    ownership = module.Ownership(42, 42, "token", "start", "exact", "digest")
    monkeypatch.setattr(module, "valid_owned_leader", lambda _value: True)
    monkeypatch.setattr(module, "group_exists", lambda _pgid: True)
    monkeypatch.setattr(module, "listener_lines", lambda: "")
    monkeypatch.setattr(
        module,
        "group_members",
        lambda _pgid: [(42, module.os.getuid()), (43, module.os.getuid())],
    )
    clock = iter([0, 11, 11, 17])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    signals = []
    monkeypatch.setattr(
        module.os, "killpg", lambda pgid, sig: signals.append((pgid, sig))
    )
    assert module.terminate_owned_group(ownership) is False
    assert signals == [(42, signal.SIGTERM), (42, signal.SIGKILL)]


def test_ui_refuses_sigkill_after_final_group_identity_changes(monkeypatch) -> None:
    module = _load("dagster_ui_reused_group", PROJECT / "scripts/dagster-ui")
    ownership = module.Ownership(42, 42, "token", "start", "exact", "digest")
    leader_checks = iter([True, False])
    monkeypatch.setattr(
        module, "valid_owned_leader", lambda _value: next(leader_checks)
    )
    monkeypatch.setattr(module, "valid_owned_group", lambda _value: False)
    monkeypatch.setattr(module, "group_exists", lambda _pgid: True)
    monkeypatch.setattr(module, "listener_lines", lambda: "occupied")
    monkeypatch.setattr(
        module,
        "group_members",
        lambda _pgid: [(42, module.os.getuid())],
    )
    clock = iter([0, 11])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    signals = []
    monkeypatch.setattr(
        module.os, "killpg", lambda pgid, sig: signals.append((pgid, sig))
    )
    assert module.terminate_owned_group(ownership) is False
    assert signals == [(42, signal.SIGTERM)]


def test_ui_listener_probe_fails_closed_and_rejects_dual_bind(monkeypatch) -> None:
    module = _load("dagster_ui_listener_probe", PROJECT / "scripts/dagster-ui")

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=2, stdout="", stderr="probe failed"
        ),
    )
    with pytest.raises(RuntimeError, match="listener probe failed"):
        module.listener_lines()
    with pytest.raises(RuntimeError, match="PID probe failed"):
        module.listener_pids()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="ambiguous failure"
        ),
    )
    with pytest.raises(RuntimeError, match="listener probe failed"):
        module.listener_lines()
    with pytest.raises(RuntimeError, match="PID probe failed"):
        module.listener_pids()

    dual = (
        "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
        "python 42 ian 10u IPv4 0 0t0 TCP 127.0.0.1:3030 (LISTEN)\n"
        "python 42 ian 11u IPv4 0 0t0 TCP 192.168.1.5:3030 (LISTEN)"
    )
    monkeypatch.setattr(module, "listener_lines", lambda: dual)
    assert module.exact_loopback_listener() is False
    assert module.wildcard_listener() is True


def test_ui_ownership_requires_all_fields_and_exact_identity(
    tmp_path, monkeypatch
) -> None:
    module = _load("dagster_ui_identity", PROJECT / "scripts/dagster-ui")
    monkeypatch.setattr(module, "PID_FILE", tmp_path / "ownership.json")
    monkeypatch.setattr(module, "foreground_digest", lambda: "sha256:foreground")
    command = f"/bin/sh {module.FOREGROUND} --ownership-token secret"
    row = (50, 50, module.os.getuid(), "Sun Aug  9 18:00:00 2026", command)
    monkeypatch.setattr(module, "process_row", lambda _pid: row)
    ownership = module.Ownership(50, 50, "secret", row[3], command, "sha256:foreground")
    module.write_ownership(ownership)
    loaded = module.read_ownership()
    assert loaded == ownership
    assert module.valid_owned_leader(loaded)
    value = module.json.loads(module.PID_FILE.read_text())
    del value["startTime"]
    module.PID_FILE.write_text(module.json.dumps(value))
    assert module.read_ownership() is None


def test_tailscale_exact_addition_and_managed_health(monkeypatch, tmp_path) -> None:
    module = _load("tailscale_add", PROJECT / "scripts/tailscale-dagster-ui")
    monkeypatch.setattr(module, "OPS", tmp_path)
    monkeypatch.setattr(module, "OWNERSHIP", tmp_path / "ownership.json")
    monkeypatch.setattr(module, "managed_local_healthy", lambda: True)
    baseline = {"TCP": {"8443": {"HTTPS": True}}, "Web": {"existing": {}}}
    statuses = iter([baseline, module.expected_with_route(baseline)])
    monkeypatch.setattr(module, "read_status", lambda: next(statuses))
    monkeypatch.setattr(module, "read_ownership", lambda: None)
    calls = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command)
        or SimpleNamespace(returncode=0),
    )
    assert module.enable() == 0
    assert calls == [
        [module.TAILSCALE, "serve", "--bg", "--https=3030", module.UPSTREAM]
    ]
    assert module.OWNERSHIP.is_file()


def test_tailscale_refuses_replaced_route_and_stale_baseline(
    monkeypatch, tmp_path
) -> None:
    module = _load("tailscale_refuse", PROJECT / "scripts/tailscale-dagster-ui")
    monkeypatch.setattr(module, "OWNERSHIP", tmp_path / "ownership.json")
    baseline = {"TCP": {}, "Web": {}}
    owned = {"baseline": baseline}
    monkeypatch.setattr(module, "read_ownership", lambda: owned)
    replaced = module.expected_with_route(baseline)
    replaced["Web"][module.PUBLIC_KEY]["Handlers"]["/"]["Proxy"] = (
        "http://127.0.0.1:9999"
    )
    monkeypatch.setattr(module, "read_status", lambda: replaced)
    calls = []
    monkeypatch.setattr(
        module.subprocess, "run", lambda *args, **kwargs: calls.append(args)
    )
    assert module.disable() == 1
    assert calls == []
    stale = module.expected_with_route({"TCP": {}, "Web": {}})
    monkeypatch.setattr(module, "read_ownership", lambda: {"baseline": stale})
    assert module.disable() == 1
    assert calls == []


def test_tailscale_invalid_addition_detects_rollback_failure(
    monkeypatch, tmp_path
) -> None:
    module = _load("tailscale_rollback", PROJECT / "scripts/tailscale-dagster-ui")
    monkeypatch.setattr(module, "OWNERSHIP", tmp_path / "ownership.json")
    monkeypatch.setattr(module, "managed_local_healthy", lambda: True)
    monkeypatch.setattr(module, "read_ownership", lambda: None)
    baseline = {"TCP": {}, "Web": {}}
    statuses = iter([baseline, {"TCP": {"3030": {"HTTPS": True}}, "Web": {}}])
    monkeypatch.setattr(module, "read_status", lambda: next(statuses))
    returns = iter([0, 9])
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=next(returns)),
    )
    assert module.enable() == 1
    assert module.OWNERSHIP.exists()


def test_tailscale_verified_disable_consumes_ownership(monkeypatch, tmp_path) -> None:
    module = _load("tailscale_disable", PROJECT / "scripts/tailscale-dagster-ui")
    monkeypatch.setattr(module, "OPS", tmp_path)
    monkeypatch.setattr(module, "OWNERSHIP", tmp_path / "ownership.json")
    baseline = {"TCP": {"8443": {"HTTPS": True}}, "Web": {"old": {}}}
    module.write_ownership(baseline)
    statuses = iter([module.expected_with_route(baseline), baseline])
    monkeypatch.setattr(module, "read_status", lambda: next(statuses))
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0),
    )
    assert module.disable() == 0
    assert not module.OWNERSHIP.exists()


def test_tailscale_script_is_scoped_and_has_no_funnel_or_reset() -> None:
    source = (PROJECT / "scripts/tailscale-dagster-ui").read_text()
    assert '"--bg"' in source
    assert '"--https=3030"' in source
    assert '"off"' in source
    assert "funnel" not in source.lower()
    assert "serve reset" not in source.lower()
    assert "set-config" not in source.lower()
    assert "http://127.0.0.1:3030" in source


def test_foreground_launcher_is_exact_loopback_and_tokenized() -> None:
    source = (PROJECT / "scripts/run-dagster-ui-foreground").read_text()
    assert "DAGSTER_HOME" in source
    assert "uv run dg dev --host 127.0.0.1 --port 3030" in source
    assert "--ownership-token" in source
    assert "0.0.0.0" not in source
