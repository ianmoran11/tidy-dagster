"""Scoped Tailnet exposure for the loopback-only data-asset status page."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / ".dagster" / "ops"
OWNERSHIP = OPS / "tailscale-data-status-3031.json"
HOSTNAME = "ians-mac-mini-1.taild519de.ts.net"
HTTPS_PORT = 3031
PUBLIC_KEY = f"{HOSTNAME}:{HTTPS_PORT}"
UPSTREAM = "http://127.0.0.1:3031"
TAILSCALE = "/usr/local/bin/tailscale"
SCHEMA = "tidy.data-status-tailscale-ownership/v1"


def main() -> int:
    os.umask(0o077)
    if len(sys.argv) != 2 or sys.argv[1] not in {"enable", "disable", "status"}:
        print(
            "Usage: scripts/tailscale-data-status-ui enable|disable|status",
            file=sys.stderr,
        )
        return 2
    if sys.argv[1] == "enable":
        return enable()
    if sys.argv[1] == "disable":
        return disable()
    current = read_status()
    print(
        json.dumps(
            {
                "localHealthy": local_healthy(),
                "ownershipPresent": read_ownership() is not None,
                "routeExact": exact_owned_route(current),
                "tailnetUrl": f"https://{PUBLIC_KEY}/",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def enable() -> int:
    if not local_healthy():
        print(
            "Refusing Tailnet enable: the local status server is not healthy.",
            file=sys.stderr,
        )
        return 1
    before = read_status()
    if has_port_route(before) or read_ownership() is not None:
        print(
            "HTTPS 3031 or its ownership record already exists; no change made.",
            file=sys.stderr,
        )
        return 1
    write_ownership(before)
    completed = subprocess.run(
        [TAILSCALE, "serve", "--bg", "--https=3031", UPSTREAM], check=False
    )
    if completed.returncode:
        if read_status() == before:
            OWNERSHIP.unlink(missing_ok=True)
        return completed.returncode
    after = read_status()
    if after != with_owned_route(before):
        rollback = subprocess.run(
            [TAILSCALE, "serve", "--https=3031", "off"], check=False
        )
        restored = rollback.returncode == 0 and read_status() == before
        if restored:
            OWNERSHIP.unlink(missing_ok=True)
            print(
                "Tailnet addition was not exact; verified rollback to baseline.",
                file=sys.stderr,
            )
        else:
            print(
                "Tailnet addition was invalid and exact rollback failed; "
                "ownership was retained for scoped recovery.",
                file=sys.stderr,
            )
        return 1
    print(f"Tailnet-only status page enabled at https://{PUBLIC_KEY}/")
    print(
        "The route persists independently; disable it explicitly when no longer needed."
    )
    return 0


def disable() -> int:
    owned = read_ownership()
    if owned is None:
        print(
            "Refusing disable without a complete status-page ownership record.",
            file=sys.stderr,
        )
        return 1
    current = read_status()
    if not has_port_route(current):
        OWNERSHIP.unlink(missing_ok=True)
        print("No HTTPS 3031 route remained; consumed the ownership record.")
        return 0
    if not exact_owned_route(current):
        print(
            "Refusing disable: the current 3031 route is not the exact owned route.",
            file=sys.stderr,
        )
        return 1
    expected = without_owned_route(current)
    completed = subprocess.run([TAILSCALE, "serve", "--https=3031", "off"], check=False)
    if completed.returncode:
        return completed.returncode
    if read_status() != expected:
        print(
            "Scoped disable did not preserve the current unrelated Serve routes.",
            file=sys.stderr,
        )
        return 1
    OWNERSHIP.unlink(missing_ok=True)
    print("HTTPS 3031 removed; unrelated Tailscale Serve routes were preserved.")
    return 0


def local_healthy() -> bool:
    try:
        with urllib.request.urlopen(f"{UPSTREAM}/healthz", timeout=1) as response:
            return response.status == 200 and response.read() == b'{"status":"ok"}\n'
    except (urllib.error.URLError, TimeoutError):
        return False


def read_status() -> dict[str, Any]:
    completed = subprocess.run(
        [TAILSCALE, "serve", "status", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("Unexpected Tailscale Serve status shape")
    return value


def has_port_route(status: dict[str, Any]) -> bool:
    return str(HTTPS_PORT) in status.get("TCP", {}) or PUBLIC_KEY in status.get(
        "Web", {}
    )


def exact_owned_route(status: dict[str, Any]) -> bool:
    return status.get("TCP", {}).get(str(HTTPS_PORT)) == {"HTTPS": True} and status.get(
        "Web", {}
    ).get(PUBLIC_KEY) == {"Handlers": {"/": {"Proxy": UPSTREAM}}}


def with_owned_route(status: dict[str, Any]) -> dict[str, Any]:
    expected = json.loads(json.dumps(status))
    expected.setdefault("TCP", {})[str(HTTPS_PORT)] = {"HTTPS": True}
    expected.setdefault("Web", {})[PUBLIC_KEY] = {
        "Handlers": {"/": {"Proxy": UPSTREAM}}
    }
    return expected


def without_owned_route(status: dict[str, Any]) -> dict[str, Any]:
    expected = json.loads(json.dumps(status))
    expected.get("TCP", {}).pop(str(HTTPS_PORT), None)
    expected.get("Web", {}).pop(PUBLIC_KEY, None)
    return expected


def baseline_digest(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def write_ownership(baseline: dict[str, Any]) -> None:
    OPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = {
        "schemaVersion": SCHEMA,
        "hostname": HOSTNAME,
        "httpsPort": HTTPS_PORT,
        "upstream": UPSTREAM,
        "baselineDigest": baseline_digest(baseline),
        "baseline": baseline,
    }
    temporary = OWNERSHIP.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    os.replace(temporary, OWNERSHIP)


def read_ownership() -> dict[str, Any] | None:
    try:
        value = json.loads(OWNERSHIP.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schemaVersion",
            "hostname",
            "httpsPort",
            "upstream",
            "baselineDigest",
            "baseline",
        }
        or value.get("schemaVersion") != SCHEMA
        or value.get("hostname") != HOSTNAME
        or value.get("httpsPort") != HTTPS_PORT
        or value.get("upstream") != UPSTREAM
        or not isinstance(value.get("baseline"), dict)
        or value.get("baselineDigest") != baseline_digest(value["baseline"])
    ):
        return None
    return value


if __name__ == "__main__":
    raise SystemExit(main())
