"""Bounded workflow authoring guide shared by AI and console copy surfaces."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_GUIDE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "architecture" / "workflow-dsl-llm-guide.md"
)
_MAX_GUIDE_BYTES = 12_000


class AuthoringGuideError(RuntimeError):
    """Raised when the trusted workflow guide cannot be loaded exactly and safely."""


@lru_cache(maxsize=1)
def workflow_authoring_guide() -> str:
    """Return the purpose-built current workflow guide verbatim."""

    try:
        guide = _GUIDE_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise AuthoringGuideError("AUTHORING_GUIDE_UNAVAILABLE") from exc
    if not guide.startswith("# AgentHub Workflow DSL — LLM Authoring Guide"):
        raise AuthoringGuideError("AUTHORING_GUIDE_INVALID")
    if len(guide.encode("utf-8")) > _MAX_GUIDE_BYTES:
        raise AuthoringGuideError("AUTHORING_GUIDE_TOO_LARGE")
    return guide
