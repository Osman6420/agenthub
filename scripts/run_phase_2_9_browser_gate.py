"""Start a disposable, synthetically seeded Django server for Playwright."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4


def main() -> None:
    workspace = Path(__file__).resolve().parents[1]
    os.chdir(workspace)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.browser_gate")
    if not os.environ.get("BROWSER_GATE_DATABASE_URL"):
        fixture_db = workspace / ".tmp" / f"agenthub_browser_gate_{uuid4().hex}.sqlite3"
        fixture_db.parent.mkdir(parents=True, exist_ok=True)
        os.environ["BROWSER_GATE_SQLITE_PATH"] = str(fixture_db)
    os.environ.setdefault(
        "BROWSER_GATE_FIXTURE_PATH", str(workspace / ".tmp" / "phase-2-9-browser-fixture.json")
    )

    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0)
    call_command("seed_phase_2_9_browser_gate", verbosity=0)
    call_command("runserver", "127.0.0.1:8011", use_reloader=False, verbosity=1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
