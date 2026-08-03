"""Provision a local, external-consumer demo without adding an application route."""

from __future__ import annotations

import http.client
import json
import os
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.artifacts.models import ArtifactVersion
from apps.artifacts.services import create_artifact_version
from apps.artifacts.types import ArtifactType
from apps.artifacts.validation import compute_checksum
from apps.catalog.models import AIProject, LifecycleStatus, Scenario, ScenarioAlias
from apps.documents import access_services
from apps.documents import services as document_services
from apps.documents.models import (
    DocumentSet,
    DocumentSetGrant,
    DocumentSetVersion,
    DocumentSetVersionStatus,
    GrantPermission,
    GrantPrincipalType,
    ScenarioDocumentSetBinding,
)
from apps.identity.capabilities import Capability
from apps.identity.models import (
    Consumer,
    ConsumerBinding,
    ConsumerProtocol,
    ConsumerStatus,
    DocumentSetResponsibility,
    DocumentSetResponsibilityAssignment,
    OrganizationResponsibility,
    OrganizationResponsibilityAssignment,
    ProjectResponsibility,
    ProjectResponsibilityAssignment,
    ScenarioResponsibility,
    ScenarioResponsibilityAssignment,
    TokenStatus,
)
from apps.identity.tokens import create_token, hash_token
from apps.ingestion.embedding_services import grant_embedding_profile, register_embedding_profile
from apps.ingestion.models import EmbeddingProfile, EmbeddingProfileStatus, IndexStatus
from apps.ingestion.staged_build import build_staged_index, promote_staged_index
from apps.orchestration.models import ModelProfile, ModelProfileStatus
from apps.orchestration.services import register_model_profile
from apps.releases.compiler import ArtifactRef, compile_release, promote_release
from apps.releases.models import ReleaseStatus
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Organization, OrganizationMembership
from apps.workflows.presets import agent_loop_workflow, document_answer_workflow, empty_workflow

ORG_SLUG = "external-demo"
PROJECT_SLUG = "public-api-showcase"
OPERATOR_USERNAME = "external-demo-admin"
EDITOR_USERNAME = "external-demo-editor"
DOC_MANAGER_USERNAME = "external-demo-doc-manager"
PLATFORM_USERNAME = "external-demo-platform"
WIKIPEDIA_DOCUMENT_ID = "wikipedia-istanbul"
WIKIPEDIA_SET_ID = "wikipedia-istanbul-kb"
MAX_WIKIPEDIA_BYTES = 1_000_000
GEMINI_SECRET_REF = "secret:gemini"  # noqa: S105 - logical reference, not a credential

SCENARIOS: dict[str, dict[str, Any]] = {
    "wikipedia-qa": {
        "name": "Wikipedia Grounded Q&A",
        "kind": "rag",
        "prompt": (
            "You answer in Turkish using only the untrusted Wikipedia excerpts supplied by the "
            "system. Give a concise factual answer and say when the excerpts are insufficient."
        ),
    },
    "wikipedia-brief": {
        "name": "Wikipedia Executive Brief",
        "kind": "rag",
        "prompt": (
            "Create a short Turkish executive brief from only the untrusted Wikipedia excerpts. "
            "Prefer dates, named places, and concrete facts; do not invent missing details."
        ),
    },
    "analysis-agent": {
        "name": "Asynchronous Analysis Agent",
        "kind": "agent",
    },
    "contract-smoke": {
        "name": "Deterministic Contract Smoke Test",
        "kind": "smoke",
    },
}

CONSUMERS: dict[str, dict[str, Any]] = {
    "research": {
        "subject": "external-research-client",
        "name": "External research client",
        "scenarios": ["wikipedia-qa", "wikipedia-brief"],
    },
    "analyst": {
        "subject": "external-analyst-client",
        "name": "External analyst client",
        "scenarios": ["analysis-agent"],
    },
    "operations": {
        "subject": "external-operations-client",
        "name": "External operations client",
        "scenarios": ["contract-smoke"],
    },
}


def fetch_wikipedia_extract(*, language: str, title: str) -> dict[str, str]:
    """Fetch one plaintext MediaWiki extract from a fixed, bounded HTTPS endpoint."""

    if language not in {"tr", "en"}:
        raise CommandError("Wikipedia language must be tr or en")
    clean_title = title.strip()
    if not clean_title or len(clean_title) > 120:
        raise CommandError("Wikipedia title is invalid")
    host = f"{language}.wikipedia.org"
    params = urlencode(
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "redirects": "1",
            "titles": clean_title,
            "format": "json",
            "formatversion": "2",
        }
    )
    connection = http.client.HTTPSConnection(host, 443, timeout=15)
    try:
        connection.request(
            "GET",
            f"/w/api.php?{params}",
            headers={"Accept": "application/json", "User-Agent": "AgentHubExternalDemo/1.0"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise CommandError(f"Wikipedia request failed with HTTP {response.status}")
        raw = response.read(MAX_WIKIPEDIA_BYTES + 1)
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise CommandError("Wikipedia request failed") from exc
    finally:
        connection.close()
    if len(raw) > MAX_WIKIPEDIA_BYTES:
        raise CommandError("Wikipedia response is too large")
    try:
        body = json.loads(raw.decode("utf-8"))
        page = body["query"]["pages"][0]
        extract = page["extract"]
        resolved_title = page["title"]
    except (KeyError, IndexError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise CommandError("Wikipedia response is invalid") from exc
    if not isinstance(extract, str) or len(extract.strip()) < 200:
        raise CommandError("Wikipedia page has no usable extract")
    if not isinstance(resolved_title, str):
        raise CommandError("Wikipedia page title is invalid")
    return {
        "title": resolved_title[:500],
        "url": f"https://{host}/wiki/{quote(resolved_title.replace(' ', '_'))}",
        "text": extract.strip(),
    }


class Command(BaseCommand):
    help = "Seed the standalone local external-consumer showcase."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--password", default="")
        parser.add_argument("--credentials-file", required=True)
        parser.add_argument("--wikipedia-title", default="İstanbul")
        parser.add_argument("--wikipedia-language", default="tr", choices=["tr", "en"])
        parser.add_argument("--refresh-wikipedia", action="store_true")
        parser.add_argument("--rotate-tokens", action="store_true")
        parser.add_argument("--no-print-secrets", action="store_true")
        parser.add_argument(
            "--model-profile-id",
            default="",
            help=(
                "Reuse an active platform ModelProfile instead of creating the local Gemini "
                "profile."
            ),
        )
        parser.add_argument(
            "--embedding-profile-id",
            default="",
            help=(
                "Reuse an active platform EmbeddingProfile instead of the deterministic local "
                "demo profile."
            ),
        )
        parser.add_argument(
            "--api-base",
            default="http://127.0.0.1:8000",
            help="Server-side AgentHub API base written to the demo credential file.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if settings.RUNTIME_MODEL_PROVIDER != (
            "apps.orchestration.providers.OpenAICompatibleModelProvider"
        ):
            raise CommandError("External demo requires the OpenAI-compatible model provider")
        model_profile_id = str(options.get("model_profile_id", "")).strip()
        embedding_profile_id = str(options.get("embedding_profile_id", "")).strip()
        if not model_profile_id and not os.environ.get("MODEL_SECRET_GEMINI"):
            raise CommandError("External demo requires --model-profile-id or MODEL_SECRET_GEMINI")
        if embedding_profile_id and settings.RUNTIME_EMBEDDING_PROVIDER != (
            "apps.ingestion.embedding.OpenAICompatibleEmbeddingClient"
        ):
            raise CommandError(
                "External demo with --embedding-profile-id requires the OpenAI-compatible "
                "embedding provider"
            )
        if not embedding_profile_id and settings.RUNTIME_EMBEDDING_PROVIDER:
            raise CommandError("External demo requires deterministic local embeddings")
        api_base = self._validate_api_base(str(options.get("api_base", "")))
        credentials_path = Path(str(options["credentials_file"])).resolve()
        existing_credentials = self._read_credentials(credentials_path)
        existing_operator = existing_credentials.get("operator", {})
        existing_password = (
            existing_operator.get("password", "") if isinstance(existing_operator, dict) else ""
        )
        password = str(
            options["password"]
            or (existing_password if isinstance(existing_password, str) else "")
            or secrets.token_urlsafe(12)
        )

        payload, tokens = self._provision(
            password=password,
            existing_credentials=existing_credentials,
            model_profile_id=model_profile_id,
            embedding_profile_id=embedding_profile_id,
            api_base=api_base,
            wikipedia_title=str(options["wikipedia_title"]),
            wikipedia_language=str(options["wikipedia_language"]),
            refresh_wikipedia=bool(options["refresh_wikipedia"]),
            rotate_tokens=bool(options["rotate_tokens"]),
        )
        self._write_credentials(credentials_path, payload)
        self.stdout.write(self.style.SUCCESS("External consumer demo ready."))
        self.stdout.write(f"credentials file: {credentials_path}")
        if not bool(options.get("no_print_secrets", False)):
            self.stdout.write(f"operator username: {OPERATOR_USERNAME}")
            self.stdout.write(f"operator password: {password}")
            for key, token in tokens.items():
                self.stdout.write(f"{key} token: {token}")

    @transaction.atomic
    def _provision(
        self,
        *,
        password: str,
        existing_credentials: dict[str, Any],
        model_profile_id: str,
        embedding_profile_id: str,
        api_base: str,
        wikipedia_title: str,
        wikipedia_language: str,
        refresh_wikipedia: bool,
        rotate_tokens: bool,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        users = self._ensure_users(password)
        organization = self._ensure_organization(users)
        project = self._ensure_project(organization, users)
        scenarios = self._ensure_scenarios(organization, project, users)
        model_profile = self._ensure_model_profile(
            users[PLATFORM_USERNAME], profile_id=model_profile_id
        )
        embedding_profile = self._ensure_embedding_profile(
            users[PLATFORM_USERNAME], organization, profile_id=embedding_profile_id
        )
        document_set = self._ensure_document_set(organization, users)
        self._ensure_scenario_document_access(document_set, scenarios, users)
        set_version = self._ensure_wikipedia_index(
            organization=organization,
            document_set=document_set,
            embedding_profile=embedding_profile,
            actor=users[DOC_MANAGER_USERNAME],
            title=wikipedia_title,
            language=wikipedia_language,
            refresh=refresh_wikipedia,
        )
        self._ensure_releases(
            organization=organization,
            scenarios=scenarios,
            model_profile=model_profile,
            set_version=set_version,
        )
        consumers = self._ensure_consumers(organization, scenarios)
        self._ensure_document_consumer_grants(document_set, consumers)
        tokens = self._ensure_tokens(
            consumers,
            existing_credentials,
            rotate=rotate_tokens,
        )
        payload = {
            "api_base": api_base,
            "operator": {"username": OPERATOR_USERNAME, "password": password},
            "consumers": {
                key: {
                    "subject": str(CONSUMERS[key]["subject"]),
                    "token": tokens[key],
                    "scenarios": list(CONSUMERS[key]["scenarios"]),
                }
                for key in CONSUMERS
            },
            "wikipedia": {
                "title": wikipedia_title,
                "language": wikipedia_language,
            },
        }
        return payload, tokens

    @staticmethod
    def _read_credentials(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _write_credentials(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            # Windows ACLs remain authoritative when POSIX mode bits are unavailable.
            pass

    @staticmethod
    def _validate_api_base(value: str) -> str:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise CommandError("api-base must be an HTTP origin without credentials or a path")
        try:
            port = parsed.port
        except ValueError as exc:
            raise CommandError("api-base port is invalid") from exc
        if port is not None and not 1 <= port <= 65535:
            raise CommandError("api-base port is invalid")
        return value.strip().rstrip("/")

    @staticmethod
    def _ensure_users(password: str) -> dict[str, Any]:
        user_model = get_user_model()
        users: dict[str, Any] = {}
        for username in (
            OPERATOR_USERNAME,
            EDITOR_USERNAME,
            DOC_MANAGER_USERNAME,
            PLATFORM_USERNAME,
        ):
            user, _created = user_model.objects.get_or_create(username=username)
            if username == OPERATOR_USERNAME:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.is_staff = username == PLATFORM_USERNAME
            user.is_superuser = username == PLATFORM_USERNAME
            user.save()
            users[username] = user
        return users

    @staticmethod
    def _ensure_organization(users: dict[str, Any]) -> Organization:
        organization, _created = Organization.objects.get_or_create(
            slug=ORG_SLUG, defaults={"name": "External Consumer Demo"}
        )
        set_tenant_context(organization.pk)
        membership, _created = OrganizationMembership.objects.get_or_create(
            organization=organization, user=users[OPERATOR_USERNAME]
        )
        OrganizationResponsibilityAssignment.objects.update_or_create(
            organization=organization,
            membership=membership,
            responsibility=OrganizationResponsibility.ADMINISTRATOR,
            defaults={"assigned_by": users[PLATFORM_USERNAME]},
        )
        for username in (EDITOR_USERNAME, DOC_MANAGER_USERNAME):
            OrganizationMembership.objects.get_or_create(
                organization=organization, user=users[username]
            )
        return organization

    @staticmethod
    def _ensure_project(organization: Organization, users: dict[str, Any]) -> AIProject:
        project, _created = AIProject.objects.get_or_create(
            organization=organization,
            slug=PROJECT_SLUG,
            defaults={"name": "Public API Showcase", "status": LifecycleStatus.ACTIVE},
        )
        membership = OrganizationMembership.objects.get(
            organization=organization, user=users[EDITOR_USERNAME]
        )
        ProjectResponsibilityAssignment.objects.update_or_create(
            organization=organization,
            project=project,
            membership=membership,
            responsibility=ProjectResponsibility.ADMINISTRATOR,
            defaults={"assigned_by": users[PLATFORM_USERNAME]},
        )
        return project

    @staticmethod
    def _ensure_scenarios(
        organization: Organization, project: AIProject, users: dict[str, Any]
    ) -> dict[str, Scenario]:
        editor_membership = OrganizationMembership.objects.get(
            organization=organization, user=users[EDITOR_USERNAME]
        )
        scenarios: dict[str, Scenario] = {}
        for alias, config in SCENARIOS.items():
            scenario, _created = Scenario.objects.update_or_create(
                project=project,
                slug=alias,
                defaults={"name": config["name"], "status": LifecycleStatus.ACTIVE},
            )
            ScenarioAlias.objects.update_or_create(
                organization=organization, alias=alias, defaults={"scenario": scenario}
            )
            ScenarioResponsibilityAssignment.objects.update_or_create(
                organization=organization,
                scenario=scenario,
                membership=editor_membership,
                responsibility=ScenarioResponsibility.EDITOR,
                defaults={"assigned_by": users[PLATFORM_USERNAME]},
            )
            scenarios[alias] = scenario
        return scenarios

    @staticmethod
    def _ensure_model_profile(actor: Any, *, profile_id: str = "") -> ModelProfile:
        if profile_id:
            try:
                return ModelProfile.objects.get(
                    public_id=profile_id, status=ModelProfileStatus.ACTIVE
                )
            except (ModelProfile.DoesNotExist, ValueError) as exc:
                raise CommandError("model profile is unavailable") from exc
        existing = ModelProfile.objects.filter(
            logical_id="external-demo-gemini", revision=1
        ).first()
        if existing is not None:
            return existing
        return register_model_profile(
            actor=actor,
            logical_id="external-demo-gemini",
            revision=1,
            provider="openai_compatible",
            scheme="https",
            host="generativelanguage.googleapis.com",
            port=443,
            path="/v1beta/openai/chat/completions",
            model="gemini-3.6-flash",
            secret_ref=GEMINI_SECRET_REF,
            timeout_seconds=30,
            max_response_bytes=1_000_000,
            max_output_tokens=1200,
        )

    @staticmethod
    def _ensure_embedding_profile(
        actor: Any, organization: Organization, *, profile_id: str = ""
    ) -> EmbeddingProfile:
        if profile_id:
            try:
                selected = EmbeddingProfile.objects.get(
                    public_id=profile_id, status=EmbeddingProfileStatus.ACTIVE
                )
            except (EmbeddingProfile.DoesNotExist, ValueError) as exc:
                raise CommandError("embedding profile is unavailable") from exc
            grant_embedding_profile(
                actor=actor, organization=organization, embedding_profile=selected
            )
            return selected
        profile = EmbeddingProfile.objects.filter(
            logical_id="external-demo-deterministic", revision=1
        ).first()
        if profile is None:
            profile = register_embedding_profile(
                actor=actor,
                logical_id="external-demo-deterministic",
                revision=1,
                provider="openai_compatible",
                scheme="https",
                host="generativelanguage.googleapis.com",
                port=443,
                path="/v1beta/openai/embeddings",
                model="deterministic-local-demo",
                secret_ref=GEMINI_SECRET_REF,
                dimensions=64,
                index_type="vector",
                normalize=True,
                distance_metric="cosine",
                timeout_seconds=15,
                max_response_bytes=1_000_000,
                max_batch_size=32,
            )
        grant_embedding_profile(actor=actor, organization=organization, embedding_profile=profile)
        return profile

    @staticmethod
    def _ensure_document_set(organization: Organization, users: dict[str, Any]) -> DocumentSet:
        document_set = DocumentSet.objects.filter(
            organization=organization, logical_id=WIKIPEDIA_SET_ID
        ).first()
        if document_set is None:
            document_set = document_services.create_document_set(
                organization=organization,
                logical_id=WIKIPEDIA_SET_ID,
                name="Wikipedia İstanbul Knowledge Base",
                actor=DOC_MANAGER_USERNAME,
            )
        membership = OrganizationMembership.objects.get(
            organization=organization, user=users[DOC_MANAGER_USERNAME]
        )
        DocumentSetResponsibilityAssignment.objects.update_or_create(
            organization=organization,
            document_set=document_set,
            membership=membership,
            responsibility=DocumentSetResponsibility.MANAGER,
            defaults={"assigned_by": users[PLATFORM_USERNAME]},
        )
        return document_set

    @staticmethod
    def _ensure_scenario_document_access(
        document_set: DocumentSet,
        scenarios: dict[str, Scenario],
        users: dict[str, Any],
    ) -> None:
        editor = users[EDITOR_USERNAME]
        manager = users[DOC_MANAGER_USERNAME]
        for alias in ("wikipedia-qa", "wikipedia-brief"):
            scenario = scenarios[alias]
            if not access_services.has_live_scenario_document_set_grant(
                scenario_id=scenario.pk, document_set_id=document_set.pk
            ):
                request = access_services.request_scenario_document_set_access(
                    scenario=scenario,
                    document_set=document_set,
                    purpose="Ground the external Wikipedia demonstration",
                    actor=editor,
                )
                access_services.approve_scenario_document_set_access(
                    access_request=request,
                    actor=manager,
                    decision_reason="Approved local public-data demonstration",
                )
            if not ScenarioDocumentSetBinding.objects.filter(
                scenario=scenario, document_set=document_set
            ).exists():
                access_services.bind_authorized_scenario_document_set(
                    scenario=scenario, document_set=document_set, actor=editor
                )

    def _ensure_wikipedia_index(
        self,
        *,
        organization: Organization,
        document_set: DocumentSet,
        embedding_profile: EmbeddingProfile,
        actor: Any,
        title: str,
        language: str,
        refresh: bool,
    ) -> DocumentSetVersion:
        active = document_set.versions.filter(
            status=DocumentSetVersionStatus.ACTIVE,
            built_index_version__status=IndexStatus.ACTIVE,
            built_index_version__embedding_profile=embedding_profile,
        ).first()
        if active is not None and not refresh:
            return active
        page = fetch_wikipedia_extract(language=language, title=title)
        draft = document_services.create_document_set_version(
            document_set=document_set, actor=DOC_MANAGER_USERNAME
        )
        markdown = (f"# {page['title']}\n\nKaynak: {page['url']}\n\n{page['text']}\n").encode()
        document_services.upload_document(
            organization=organization,
            logical_id=WIKIPEDIA_DOCUMENT_ID,
            title=page["title"],
            mime_type="text/markdown",
            data=markdown,
            actor=actor.get_username(),
            document_set_version=draft,
        )
        published = document_services.publish_document_set_version(
            set_version=draft, actor=actor.get_username()
        )
        chunking = self._artifact(
            organization,
            ArtifactType.CHUNKING_PROFILE,
            "external-demo.chunking",
            {
                "api_version": "agenthub/chunking/v1",
                "kind": "ChunkingProfile",
                "strategy": "headings",
                "size": 1200,
                "overlap": 120,
                "max_chunks": 500,
            },
        )
        retrieval = self._artifact(
            organization,
            ArtifactType.RETRIEVAL_PROFILE,
            "external-demo.retrieval",
            {
                "api_version": "agenthub/retrieval/v1",
                "kind": "RetrievalProfile",
                "mode": "hybrid",
                "top_k": 6,
                "score_threshold": 0.0,
                "vector_weight": 0.45,
                "keyword_weight": 0.55,
            },
        )
        index = build_staged_index(
            document_set_version=published,
            embedding_profile=embedding_profile,
            chunking_profile=chunking,
            retrieval_profile=retrieval,
            actor=actor.get_username(),
        )
        served = promote_staged_index(index, actor=actor.get_username())
        if served.document_set_version is None:
            raise CommandError("Served index lost its document-set version")
        return served.document_set_version

    def _ensure_releases(
        self,
        *,
        organization: Organization,
        scenarios: dict[str, Scenario],
        model_profile: ModelProfile,
        set_version: DocumentSetVersion,
    ) -> None:
        model_artifact = self._artifact(
            organization,
            ArtifactType.MODEL_PROFILE,
            "external-demo.model",
            {"profile_id": str(model_profile.public_id)},
        )
        retrieval_artifact = self._artifact(
            organization,
            ArtifactType.RETRIEVAL_PROFILE,
            "external-demo.retrieval",
            {
                "api_version": "agenthub/retrieval/v1",
                "kind": "RetrievalProfile",
                "mode": "hybrid",
                "top_k": 6,
                "score_threshold": 0.0,
                "vector_weight": 0.45,
                "keyword_weight": 0.55,
            },
        )
        for alias, scenario in scenarios.items():
            config = SCENARIOS[alias]
            active = scenario.releases.filter(status=ReleaseStatus.ACTIVE).first()
            active_artifacts = active.manifest.get("artifacts", {}) if active is not None else {}
            active_model = (
                active_artifacts.get("model_profile", {})
                if isinstance(active_artifacts, dict)
                else {}
            )
            model_matches = config["kind"] == "smoke" or (
                isinstance(active_model, dict)
                and active_model.get("checksum") == model_artifact.checksum
            )
            if (
                active is not None
                and (
                    alias not in {"wikipedia-qa", "wikipedia-brief"}
                    or set_version.pk in active.manifest.get("document_set_versions", [])
                )
                and model_matches
            ):
                continue
            refs: list[ArtifactRef] = []
            input_contract = self._artifact(
                organization,
                ArtifactType.INPUT_CONTRACT,
                f"{alias}.input",
                {
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "string", "minLength": 1}},
                    "additionalProperties": False,
                },
            )
            output_contract = self._artifact(
                organization,
                ArtifactType.OUTPUT_CONTRACT,
                f"{alias}.output",
                {
                    "type": "object",
                    "required": ["answer", "sources"],
                    "properties": {
                        "answer": {"type": "string"},
                        "sources": {"type": "array"},
                    },
                    "additionalProperties": True,
                },
            )
            if config["kind"] == "rag":
                workflow_body = document_answer_workflow(logical_id=f"{alias}.v1")
                prompt = self._artifact(
                    organization,
                    ArtifactType.PROMPT_TEMPLATE,
                    f"{alias}.prompt",
                    {"template": config["prompt"]},
                )
                refs.extend(
                    [
                        self._ref("prompt", prompt),
                        self._ref("model_profile", model_artifact),
                        self._ref("retrieval_profile", retrieval_artifact),
                    ]
                )
            elif config["kind"] == "agent":
                workflow_body = agent_loop_workflow(
                    logical_id=f"{alias}.v1",
                    policy={
                        "tool_binding_roles": [],
                        "retrieval": {"enabled": False},
                        "limits": {
                            "max_steps": 4,
                            "max_tool_calls": 0,
                            "max_tokens": 4096,
                            "deadline_seconds": 60,
                        },
                    },
                )
                refs.append(self._ref("model_profile", model_artifact))
            else:
                workflow_body = empty_workflow(logical_id=f"{alias}.v1")
            workflow = self._artifact(
                organization,
                ArtifactType.WORKFLOW_DEFINITION,
                f"{alias}.workflow",
                workflow_body,
            )
            refs.extend(
                [
                    self._ref("input_contract", input_contract),
                    self._ref("output_contract", output_contract),
                    self._ref("workflow_definition", workflow),
                ]
            )
            release = compile_release(
                scenario=scenario,
                refs=refs,
                runtime_version="workflow:1",
                created_by=EDITOR_USERNAME,
            )
            promote_release(release)

    @staticmethod
    def _artifact(
        organization: Organization, artifact_type: str, logical_id: str, body: dict[str, Any]
    ) -> ArtifactVersion:
        checksum = compute_checksum(body)
        existing = ArtifactVersion.objects.filter(
            organization=organization,
            type=artifact_type,
            logical_id=logical_id,
            checksum=checksum,
        ).first()
        if existing is not None:
            return existing
        return create_artifact_version(
            organization=organization,
            artifact_type=artifact_type,
            logical_id=logical_id,
            body=body,
            created_by=EDITOR_USERNAME,
        )

    @staticmethod
    def _ref(role: str, artifact: ArtifactVersion) -> ArtifactRef:
        return ArtifactRef(role, artifact.type, artifact.logical_id, artifact.version)

    @staticmethod
    def _ensure_consumers(
        organization: Organization, scenarios: dict[str, Scenario]
    ) -> dict[str, Consumer]:
        result: dict[str, Consumer] = {}
        for key, config in CONSUMERS.items():
            consumer, _created = Consumer.objects.update_or_create(
                organization=organization,
                subject=config["subject"],
                defaults={
                    "name": config["name"],
                    "protocol": ConsumerProtocol.REST,
                    "status": ConsumerStatus.ACTIVE,
                },
            )
            allowed = {scenarios[alias].pk for alias in config["scenarios"]}
            ConsumerBinding.objects.filter(consumer=consumer).exclude(
                scenario_id__in=allowed
            ).update(status="disabled")
            for alias in config["scenarios"]:
                ConsumerBinding.objects.update_or_create(
                    consumer=consumer,
                    scenario=scenarios[alias],
                    defaults={
                        "organization": organization,
                        "capabilities": [Capability.WORKFLOW_RUN],
                        "status": "active",
                    },
                )
            result[key] = consumer
        return result

    @staticmethod
    def _ensure_document_consumer_grants(
        document_set: DocumentSet, consumers: dict[str, Consumer]
    ) -> None:
        for key in ("research",):
            consumer = consumers[key]
            if not DocumentSetGrant.objects.filter(
                document_set=document_set,
                principal_type=GrantPrincipalType.CONSUMER,
                principal_ref=str(consumer.pk),
                permission=GrantPermission.RETRIEVE,
            ).exists():
                document_services.grant_document_set(
                    document_set=document_set,
                    principal_type=GrantPrincipalType.CONSUMER,
                    principal_ref=str(consumer.pk),
                    actor=DOC_MANAGER_USERNAME,
                )

    @staticmethod
    def _ensure_tokens(
        consumers: dict[str, Consumer], existing: dict[str, Any], *, rotate: bool
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        existing_consumers = existing.get("consumers", {})
        for key, consumer in consumers.items():
            raw = ""
            entry = existing_consumers.get(key, {}) if isinstance(existing_consumers, dict) else {}
            candidate = entry.get("token", "") if isinstance(entry, dict) else ""
            if isinstance(candidate, str) and not rotate:
                valid = consumer.tokens.filter(
                    token_hash=hash_token(candidate), status=TokenStatus.ACTIVE
                ).exists()
                raw = candidate if valid else ""
            if not raw:
                if rotate:
                    consumer.tokens.filter(status=TokenStatus.ACTIVE).update(
                        status=TokenStatus.REVOKED
                    )
                _record, raw = create_token(consumer, f"external-demo-{key}-{secrets.token_hex(3)}")
            result[key] = raw
        return result
