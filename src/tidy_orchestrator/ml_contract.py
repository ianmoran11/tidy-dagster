"""Cross-language canonical encoding for local ML contract digests.

Canonical JSON v1 sorts object keys by UTF-8 bytes, emits strings as UTF-8 JSON
without ASCII escaping, and emits every finite number as a normalized IEEE-754
binary64 scientific decimal with exactly 17 fractional digits. Negative zero is
canonicalized to positive zero. Booleans are not numbers.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


class CanonicalEncodingError(ValueError):
    """A value is outside canonical-json-v1."""


def canonical_json_v1(value: Any) -> bytes:
    return _encode(value).encode("utf-8")


def canonical_digest_v1(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_v1(value)).hexdigest()


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int | float):
        number = float(value)
        if not math.isfinite(number):
            raise CanonicalEncodingError("canonical numbers must be finite binary64")
        if number == 0:
            number = 0.0
        mantissa, exponent = format(number, ".17e").split("e")
        return f"{mantissa}e{int(exponent):+d}"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list | tuple):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise CanonicalEncodingError("canonical object keys must be strings")
        keys = sorted(value, key=lambda key: key.encode("utf-8"))
        return (
            "{"
            + ",".join(f"{_encode(key)}:{_encode(value[key])}" for key in keys)
            + "}"
        )
    raise CanonicalEncodingError(f"unsupported canonical value: {type(value).__name__}")
