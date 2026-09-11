"""Phase 2.9 Part 7 browser-gate safety coverage."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_browser_fixture_seed_refuses_normal_application_settings() -> None:
    with pytest.raises(CommandError, match="guarded browser_gate settings"):
        call_command("seed_phase_2_9_browser_gate", verbosity=0)
