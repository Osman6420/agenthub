"""Minimal subprocess worker for the P2.6.8 test harness.

This module is not a production sandbox. The parent starts it with a scrubbed environment and
passes one bounded request on stdin. It deliberately returns stable reason codes only.
"""

from __future__ import annotations

import json
import sys
import tracemalloc
from typing import Any


def _main() -> int:
    try:
        request = json.loads(sys.stdin.buffer.read())
        memory_bytes = int(request["memory_bytes"])
        _apply_posix_memory_limit(memory_bytes)
        tracemalloc.start()
        allowed_modules = frozenset(request["requested_modules"])

        def safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            root = name.split(".", 1)[0]
            if root not in allowed_modules:
                raise ImportError
            return __import__(name)

        safe_builtins = {
            "__import__": safe_import,
            "abs": abs,
            "all": all,
            "any": any,
            "bool": bool,
            "dict": dict,
            "enumerate": enumerate,
            "float": float,
            "int": int,
            "len": len,
            "list": list,
            "max": max,
            "min": min,
            "range": range,
            "round": round,
            "set": set,
            "sorted": sorted,
            "str": str,
            "sum": sum,
            "tuple": tuple,
            "zip": zip,
        }
        namespace: dict[str, Any] = {"__builtins__": safe_builtins}
        exec(compile(request["source"], "<python-node>", "exec"), namespace, namespace)  # noqa: S102
        entrypoint = namespace.get("run")
        if not callable(entrypoint):
            return _emit("PYTHON_NODE_ENTRYPOINT_INVALID")
        result = entrypoint(request["config"], request["input"])
        _, peak = tracemalloc.get_traced_memory()
        if peak > memory_bytes:
            return _emit("PYTHON_NODE_MEMORY_LIMIT")
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > int(request["output_bytes"]):
            return _emit("PYTHON_NODE_OUTPUT_LIMIT")
        sys.stdout.buffer.write(
            json.dumps({"status": "ok", "output": result}, ensure_ascii=False).encode("utf-8")
        )
        return 0
    except MemoryError:
        return _emit("PYTHON_NODE_MEMORY_LIMIT")
    except BaseException:  # stable, content-free boundary; never return tenant exception text
        return _emit("PYTHON_NODE_EXECUTION_FAILED")


def _apply_posix_memory_limit(memory_bytes: int) -> None:
    try:
        import resource
    except ImportError:
        return
    setrlimit = getattr(resource, "setrlimit", None)
    address_space_limit = getattr(resource, "RLIMIT_AS", None)
    if not callable(setrlimit) or address_space_limit is None:
        return
    setrlimit(address_space_limit, (memory_bytes, memory_bytes))


def _emit(code: str) -> int:
    sys.stdout.buffer.write(json.dumps({"status": "error", "code": code}).encode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
