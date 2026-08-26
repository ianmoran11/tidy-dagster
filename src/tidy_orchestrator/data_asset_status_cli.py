from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .data_asset_status import (
    DEFAULT_REGISTRY,
    DataAssetStatusError,
    build_asset_csv_payloads,
    default_project_root,
    make_status_server,
    refresh_snapshot,
    snapshot_matches,
)
from .offenders_acceptance import c4_shared_access


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="build and serve the read-only Tidy Data Asset Status page"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=default_project_root(),
        help="repository root (defaults to the source repository)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY,
        help="registry path relative to the project root",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "refresh", help="regenerate the deterministic committed HTML snapshot"
    )
    commands.add_parser("check", help="verify that the committed snapshot is current")
    commands.add_parser(
        "serve", help="refresh, then serve the page in the foreground on loopback"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        if arguments.command == "refresh":
            status, output, changed = refresh_snapshot(
                arguments.project_root, arguments.registry
            )
            state = "updated" if changed else "already current"
            print(
                f"Status snapshot {state}: {output} "
                f"({len(status.assets)} sheet-assets)."
            )
            return 0
        if arguments.command == "check":
            matches, output, expected, actual = snapshot_matches(
                arguments.project_root, arguments.registry
            )
            if not matches:
                print(
                    f"Status snapshot is stale: {output}\n"
                    f"expected {expected}\nactual {actual or 'missing'}",
                    file=sys.stderr,
                )
                return 1
            print(f"Status snapshot matches evidence: {output} ({expected}).")
            return 0
        with c4_shared_access(arguments.project_root):
            status, output, _changed = refresh_snapshot(
                arguments.project_root, arguments.registry
            )
            csv_payloads = build_asset_csv_payloads(arguments.project_root, status)
            html_payload = output.read_bytes()
        server = make_status_server(
            status.host, status.port, html_payload, csv_payloads
        )
        print(
            f"Tidy Data Asset Status: http://{status.host}:{status.port}/ "
            f"({len(csv_payloads)} asset CSV routes)"
        )
        print(
            "Tailnet (when explicitly enabled): "
            f"https://{status.tailnet_hostname}:{status.tailnet_https_port}/"
        )
        print("Press Ctrl-C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStatus server stopped.")
        finally:
            server.server_close()
        return 0
    except DataAssetStatusError as error:
        print(f"status interface error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
