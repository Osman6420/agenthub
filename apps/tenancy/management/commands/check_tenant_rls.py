from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.tenancy.rls import inspect_rls_readiness, tenant_table_inventory


class Command(BaseCommand):
    help = "Read-only ADR-0004 RLS/application-role deployment-readiness check."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--app-role", required=True)
        parser.add_argument("--schema", default="public")
        parser.add_argument("--database", default="default")
        parser.add_argument("--shared-vectors-only", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        inventory = tenant_table_inventory()
        for table in inventory:
            self.stdout.write(
                "\t".join(
                    (
                        table.classification.value,
                        table.model_label,
                        table.table_name,
                        table.tenant_column or "indirect",
                        "nullable" if table.nullable else "required",
                    )
                )
            )
        try:
            report = inspect_rls_readiness(
                app_role=options["app_role"],
                schema=options["schema"],
                using=options["database"],
                shared_vectors_only=options["shared_vectors_only"],
            )
        except (RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if not report.ready:
            for issue in report.issues:
                self.stderr.write(issue)
            raise CommandError(f"RLS_NOT_READY ({len(report.issues)} issues)")
        self.stdout.write(
            self.style.SUCCESS(
                f"RLS_READY role={report.role.name} protected_tables={len(report.tables)}"
            )
        )
