from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.documents.models import DocumentSetVersion
from apps.ingestion.models import EmbeddingProfile, OcrProfile
from apps.ingestion.ocr import OcrError
from apps.ingestion.staged_build import StagedBuildError, build_staged_index


class Command(BaseCommand):
    help = "Build a staged blue/green real-embedding index for a published document-set version."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--actor", required=True)
        parser.add_argument("--document-set-version", type=int, required=True)
        parser.add_argument("--profile-id", required=True, help="EmbeddingProfile public_id")
        parser.add_argument("--ocr-profile-id", help="OcrProfile public_id for image-only PDFs")

    def handle(self, *args: Any, **options: Any) -> None:
        set_version = DocumentSetVersion.objects.filter(pk=options["document_set_version"]).first()
        if set_version is None:
            raise CommandError("document-set version not found")
        profile = EmbeddingProfile.objects.filter(public_id=options["profile_id"]).first()
        if profile is None:
            raise CommandError("embedding profile not found")
        ocr_profile = None
        if options.get("ocr_profile_id"):
            ocr_profile = OcrProfile.objects.filter(public_id=options["ocr_profile_id"]).first()
            if ocr_profile is None:
                raise CommandError("OCR profile not found")
        try:
            index_version = build_staged_index(
                document_set_version=set_version,
                embedding_profile=profile,
                actor=options["actor"],
                ocr_profile=ocr_profile,
            )
        except (StagedBuildError, OcrError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"built staged IndexVersion {index_version.pk} "
                f"(status={index_version.status}, chunks={index_version.chunk_count})"
            )
        )
