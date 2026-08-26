"""Disposable tiny-payload driver for the real C4 install transaction state machine."""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace


def _module():
    path = Path(__file__).parents[1] / "scripts/register-offenders-remaining.py"
    spec = importlib.util.spec_from_file_location("c4_matrix_registration", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    event = sys.argv[2]
    signal_name = sys.argv[3] if len(sys.argv) > 3 else "exception"
    module = _module()
    module.ROOT = root
    module.TX_ROOT = root / ".product-prototype/offenders-c4-install-transactions"
    module.TX_LOCK = module.TX_ROOT / "install.lock"
    (root / ".product-prototype").mkdir(parents=True)
    (root / "docs/data-asset-status").mkdir(parents=True)
    run = root / "proposal"
    (run / "payload").mkdir(parents=True)
    (run / "manifest.json").write_text("{}")
    proposal = {
        "families": 47,
        "members": 170,
        "rows": 224997,
        "payloadRootDigest": "sha256:" + "a" * 64,
        "outputRootDigest": "sha256:" + "b" * 64,
        "files": [],
    }
    (run / "manifest.json").write_text(json.dumps(proposal))
    snapshot = b"snapshot"
    authority = {
        "proposal": {key: proposal[key] for key in proposal if key != "files"},
        "installedInputClosure": [],
        "generatedOutputClosure": [
            {
                "path": "docs/data-asset-status/index.html",
                "byteLength": len(snapshot),
                "sha256": module._sha(snapshot),
            }
        ],
    }
    module.verify_c4_acceptance_authority = lambda *_args, **_kwargs: authority
    module.validate_manifest = lambda _run: proposal
    module._authorized_installed_pins = lambda *_args: []
    original_write_durable = module._write_durable

    def injected_write(path: Path, value: object) -> None:
        if event == "initial-owner-failure" and path.name == "owner.json":
            raise OSError("injected initial owner failure")
        if (
            event == "initial-journal-failure"
            and path.name == "journal.json"
            and isinstance(value, dict)
            and value.get("phase") == "staging"
        ):
            raise OSError("injected initial journal failure")
        original_write_durable(path, value)

    module._write_durable = injected_write

    def replacements(payload: Path):
        if event == "staging-signal":
            os.kill(os.getpid(), getattr(signal, signal_name))
        items = []
        sources = payload / "matrix-sources"
        sources.mkdir()
        destinations = root / "matrix-destinations"
        destinations.mkdir()
        for index in range(315):
            source = sources / f"{index:03d}"
            destination = destinations / f"{index:03d}"
            source.write_text(f"new-{index}")
            destination.write_text(f"prior-{index}")
            items.append(("cohort", source, destination))
        return items

    module._replacement_items = replacements
    module._expected_destination_paths = lambda _manifest: [
        *(f"matrix-destinations/{index:03d}" for index in range(315)),
        "docs/data-asset-status/index.html",
    ]
    module._verify_installed = lambda _manifest: None
    module.verify_offenders_release = lambda _root: {
        "registeredMemberCount": 190,
        "pendingSemanticContractCount": 0,
    }
    registry = SimpleNamespace(
        entries=tuple(SimpleNamespace(replay_engine=None) for _ in range(288)),
        worksheet_count=798,
    )
    module.load_large_batch_registry = lambda _root: registry
    module.verify_batch_normalization = lambda *_args: None
    module.build_dashboard = lambda _root: SimpleNamespace(
        cohorts=tuple(range(293)),
        assets=tuple(
            SimpleNamespace(canonical_count=751237 if index == 0 else 0)
            for index in range(823)
        ),
    )
    module.render_dashboard = lambda _dashboard: snapshot
    module.snapshot_matches = lambda _root: (True, None, None, None)
    if event == "rollback-failure":
        module._rollback = lambda *_args: ["injected sole-backup restoration failure"]
    observed_hooks: list[str] = []

    def inject(observed: str, _path: Path) -> None:
        if observed in module.transaction_hook_names():
            observed_hooks.append(observed)
        if event == "record-rollback-hooks" and observed == "post-swap-validation":
            raise RuntimeError("record rollback hook reachability")
        if event == "rollback-interruption" and observed == "before-install-0":
            raise RuntimeError("trigger rollback for interruption hook")
        target = "before-install-0" if event == "rollback-failure" else event
        if observed != target:
            return
        if signal_name == "exception":
            raise RuntimeError(f"injected {event}")
        os.kill(os.getpid(), getattr(signal, signal_name))
        if event == "rollback-interruption":
            raise RuntimeError("trigger rollback after queued signal")

    try:
        module.install(run, "sha256:" + "c" * 64, inject)
    except BaseException as error:
        print(type(error).__name__, str(error), file=sys.stderr)
    state = root / "matrix-state.json"
    destinations = root / "matrix-destinations"
    values = [path.read_text() for path in sorted(destinations.glob("*"))]
    lock = module.TX_LOCK
    transactions = (
        sorted(module.TX_ROOT.glob("transaction-*")) if module.TX_ROOT.exists() else []
    )
    state.parent.mkdir(parents=True, exist_ok=True)
    if event in {"record-hooks", "record-rollback-hooks"}:
        (root / "matrix-hooks.json").write_text(json.dumps(observed_hooks))
    state.write_text(
        json.dumps(
            {
                "prior": values == [f"prior-{index}" for index in range(315)],
                "complete": values == [f"new-{index}" for index in range(315)],
                "lock": lock.is_file(),
                "transactions": [path.name for path in transactions],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
