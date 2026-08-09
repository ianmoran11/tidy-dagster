#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

scenario = sys.argv[1]
parser = argparse.ArgumentParser()
parser.add_argument("--marker")
parser.add_argument("--pid-file")
parser.add_argument("--port", type=int)
parser.add_argument("--request", required=True)
parser.add_argument("--input-root", required=True)
parser.add_argument("--output-root", required=True)
args = parser.parse_args(sys.argv[2:])
if args.marker:
    Path(args.marker).write_text("started")
request = json.loads(Path(args.request).read_text())
output = Path(args.output_root)
request_id = request["requestId"]


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def descriptor(path: str, data: bytes, **changes):
    value = {
        "name": path,
        "relativePath": path,
        "contentDigest": digest(data),
        "byteLength": len(data),
    }
    value.update(changes)
    return value


def success(outputs):
    return {
        "protocolVersion": "tidy.worker/v1",
        "requestId": request_id,
        "ok": True,
        "outputs": outputs,
        "warnings": [],
    }


def write(path: str, data: bytes) -> None:
    target = output / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


if scenario == "malformed":
    sys.stdout.write("not-json\n")
    raise SystemExit(0)
if scenario == "stdout-large":
    sys.stdout.write("x" * 2_000_000)
    raise SystemExit(0)
if scenario == "stderr-large":
    sys.stderr.write("x" * 2_000_000)
    raise SystemExit(7)
if scenario == "nonzero":
    raise SystemExit(7)
if scenario == "timeout":
    time.sleep(60)
if scenario == "grandchild":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(args.pid_file).write_text(str(child.pid))
    time.sleep(60)
if scenario == "success-grandchild":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    Path(args.pid_file).write_text(str(child.pid))
if scenario == "detached-probe":
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        start_new_session=True,
    )
    Path(args.pid_file).write_text(str(child.pid))
if scenario == "network-probe":
    with socket.create_connection(("127.0.0.1", args.port), timeout=1):
        pass
if scenario == "domain-error":
    print(
        json.dumps(
            {
                "protocolVersion": "tidy.worker/v1",
                "requestId": request_id,
                "ok": False,
                "error": {"code": "SYNTHETIC", "stage": "execute", "message": "no"},
            }
        )
    )
    raise SystemExit(1)

payload = b"provider-free-output"
if scenario == "producer-drift":
    Path(__file__).write_bytes(Path(__file__).read_bytes() + b"\n")
if scenario == "drift-output":
    payload = os.urandom(32)
normal = descriptor("result.json", payload)
if scenario in (
    "success",
    "mark-success",
    "success-grandchild",
    "detached-probe",
    "drift-output",
    "producer-drift",
):
    write("result.json", payload)
    response = success([normal])
elif scenario == "unknown-protocol":
    write("result.json", payload)
    response = success([normal])
    response["protocolVersion"] = "tidy.worker/v2"
elif scenario == "unknown-field":
    write("result.json", payload)
    response = success([normal])
    response["extra"] = True
elif scenario == "duplicate-json-key":
    write("result.json", payload)
    raw = json.dumps(success([normal]), separators=(",", ":"))
    print(raw[:-1] + ',"ok":true}')
    raise SystemExit(0)
elif scenario == "nonfinite-json":
    write("result.json", payload)
    response = success([normal])
    response["warnings"] = [{"code": "BAD", "message": float("nan")}]
elif scenario == "warning-overflow":
    write("result.json", payload)
    response = success([normal])
    response["warnings"] = [{"code": "W", "message": ""}] * 2
elif scenario == "path-traversal":
    response = success([descriptor("../escape", payload)])
elif scenario == "absolute-path":
    response = success([descriptor("/tmp/escape", payload)])
elif scenario == "symlink":
    os.symlink(args.request, output / "result.json")
    response = success([normal])
elif scenario == "undeclared":
    write("result.json", payload)
    write("extra.txt", b"extra")
    response = success([normal])
elif scenario == "digest-mismatch":
    write("result.json", payload)
    response = success(
        [descriptor("result.json", payload, contentDigest=digest(b"wrong"))]
    )
elif scenario == "length-mismatch":
    write("result.json", payload)
    response = success(
        [descriptor("result.json", payload, byteLength=len(payload) + 1)]
    )
elif scenario == "output-size":
    payload = b"x" * 2048
    write("result.json", payload)
    response = success([descriptor("result.json", payload)])
elif scenario == "output-count":
    write("one", b"1")
    write("two", b"2")
    response = success([descriptor("one", b"1"), descriptor("two", b"2")])
else:
    raise RuntimeError(f"unknown scenario {scenario}")
print(json.dumps(response, separators=(",", ":")))
