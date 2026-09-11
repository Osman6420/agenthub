"""Transport-neutral governed execution result used by evaluation assertions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RunResult:
    status: str
    output: dict[str, Any]
    usage: dict[str, int]
    fallback_used: bool
    metadata: dict[str, Any] = field(default_factory=dict)
