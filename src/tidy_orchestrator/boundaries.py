"""Static guard against Python runtime dependency on sibling source worktrees."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_FORBIDDEN_MODULE_PARTS = ("tidycell", "tidybank", "sembla", "justice")
_PATH_CALLS = {
    "open",
    "read_text",
    "read_bytes",
    "write_text",
    "write_bytes",
    "run",
    "Popen",
}


def scan_file(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    failures: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            if any(part in module.lower() for part in _FORBIDDEN_MODULE_PARTS):
                failures.append(f"{path}: forbidden sibling import {module}")
        if isinstance(node, ast.Call) and node.args:
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            argument = node.args[0]
            if (
                name in _PATH_CALLS
                and isinstance(argument, ast.Constant)
                and isinstance(argument.value, str)
                and _forbidden_path(argument.value)
            ):
                failures.append(
                    f"{path}:{node.lineno}: forbidden literal path {argument.value}"
                )
    if "/" + "Users/" in source or "C:" + "\\Users\\" in source:
        failures.append(f"{path}: absolute workstation path")
    return failures


def scan_roots(roots: tuple[Path, ...]) -> list[str]:
    failures: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            failures.extend(scan_file(path))
    return failures


def _forbidden_path(value: str) -> bool:
    lowered = value.lower()
    return (
        value.startswith(("/", "../"))
        or "\\users\\" in lowered
        or any(part in lowered for part in _FORBIDDEN_MODULE_PARTS)
    )


def main() -> int:
    failures = scan_roots((Path("src"), Path("scripts")))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("python-boundary-check: no sibling imports or workstation paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
