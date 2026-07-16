"""Public gateway endpoints (v3 plan §11).

Flow for invoke/query: authenticate consumer -> authorize scenario alias +
capability -> resolve the active release -> validate input against the release input
contract -> honor idempotency -> issue a signed ExecutionContext -> dispatch to the
runtime facade -> audit + usage. Everything is fail-closed and returns the standard
error envelope.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import jsonschema
from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.compiler import AgentCompileError
from apps.agents.models import AgentRun, AgentRunStatus
from apps.agents.services import (
    AgentRequestError,
    cancel_agent_run,
    request_agent_run,
    resolve_release_agent,
)
from apps.agents.tasks import execute_agent_run
from apps.artifacts.validation import compute_checksum
from apps.audit.services import record_event
from apps.catalog.models import ScenarioType
from apps.gateway.errors import ApiError, ErrorCode
from apps.gateway.execution_context import issue_execution_context
from apps.gateway.models import IdempotencyRecord
from apps.gateway.openai_compat import (
    chat_response,
    compatible_error,
    parse_chat_request,
    parse_responses_request,
    prepare_runtime_input,
    responses_response,
)
from apps.gateway.runtime import dispatch
from apps.identity.capabilities import Capability
from apps.identity.models import ConsumerProtocol
from apps.identity.services import resolve_active_binding
from apps.observability.models import UsageEvent
from apps.releases.routing import select_release
from apps.releases.services import get_artifact_body_for_role
from apps.workflows.compiler import WorkflowCompileError
from apps.workflows.models import WorkflowRun, WorkflowRunStatus
from apps.workflows.services import (
    WorkflowRequestError,
    cancel_workflow_run,
    request_workflow_run,
    resolve_release_workflow,
)
from apps.workflows.tasks import execute_workflow_run

_QUERY_CAPABILITY = Capability.QUERY


def _require_mapping(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "Request body must be a JSON object.",
            http_status_code=400,
        )
    return data


def _require_alias(data: dict[str, Any]) -> str:
    alias = data.get("scenario_alias")
    # Only a bound alias routes; raw project_id/release_id in the body are ignored.
    if not isinstance(alias, str) or not alias:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "scenario_alias is required.",
            http_status_code=400,
        )
    return alias


def _validate_input(release: Any, input_payload: dict[str, Any]) -> None:
    schema = get_artifact_body_for_role(release, "input_contract")
    if schema is None:
        return
    try:
        jsonschema.validate(instance=input_payload, schema=schema)
    except jsonschema.ValidationError as exc:
        # Do not echo the offending value; report only the location.
        raise ApiError(
            ErrorCode.INPUT_CONTRACT_VIOLATION,
            "Input does not satisfy the scenario input contract.",
            http_status_code=400,
            details=[{"path": [str(p) for p in exc.absolute_path]}],
        ) from None


class _GatewayView(APIView):
    """Shared authorization + dispatch pipeline for invoke/query."""

    operation = "invoke"
    required_protocol = ConsumerProtocol.REST

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Return (scenario_alias, input_payload). Overridden by the query facade."""
        alias = _require_alias(data)
        payload = data.get("input")
        if not isinstance(payload, dict):
            raise ApiError(
                ErrorCode.VALIDATION_ERROR, "input must be an object.", http_status_code=400
            )
        return alias, payload

    def post(self, request: Request) -> Response:
        started = time.monotonic()
        consumer = request.auth  # set by ConsumerTokenAuthentication
        if consumer.protocol != self.required_protocol:
            request_id = getattr(request, "request_id", "")
            self._record_usage(consumer, request_id, "", ErrorCode.CAPABILITY_DENIED, started)
            record_event(
                actor_type="consumer",
                actor_id=consumer.subject,
                action=f"gateway.{self.operation}",
                outcome="deny",
                organization_id=consumer.organization_id,
                resource_type="consumer",
                resource_id=str(consumer.public_id),
                reason="PROTOCOL_DENIED",
                request_id=request_id,
            )
            raise ApiError(
                ErrorCode.CAPABILITY_DENIED,
                "The credential is not enabled for this protocol.",
                http_status_code=403,
            )
        request_id = getattr(request, "request_id", "")
        alias = ""
        try:
            try:
                content_length = int(request.META.get("CONTENT_LENGTH") or 0)
            except (TypeError, ValueError):
                content_length = settings.GATEWAY_MAX_REQUEST_BYTES + 1
            if content_length > settings.GATEWAY_MAX_REQUEST_BYTES:
                raise ApiError(
                    ErrorCode.VALIDATION_ERROR,
                    "The request body is too large.",
                    http_status_code=413,
                )
            data = _require_mapping(request.data)
            alias, input_payload = self._extract(data)
            response = self._process(request, consumer, request_id, alias, input_payload)
        except ApiError as exc:
            self._record_usage(consumer, request_id, alias, exc.code, started)
            record_event(
                actor_type="consumer",
                actor_id=consumer.subject,
                action=f"gateway.{self.operation}",
                outcome="deny",
                organization_id=consumer.organization_id,
                resource_type="scenario_alias",
                resource_id=alias,
                reason=exc.code,
                request_id=request_id,
            )
            raise
        return response

    def _process(
        self,
        request: Request,
        consumer: Any,
        request_id: str,
        alias: str,
        input_payload: dict[str, Any],
    ) -> Response:
        # Authorize alias + capability against the consumer's bindings.
        resolved = resolve_active_binding(
            organization_id=consumer.organization_id, subject=consumer.subject, alias=alias
        )
        if resolved is None:
            raise ApiError(
                ErrorCode.SCENARIO_NOT_ALLOWED,
                "The scenario alias is not available to this consumer.",
                http_status_code=403,
            )
        scenario = resolved.binding.scenario
        dispatch_kind = self._dispatch_kind(scenario, input_payload)
        if dispatch_kind == "workflow":
            required_capability = Capability.WORKFLOW_RUN
        elif dispatch_kind == "agent":
            required_capability = Capability.AGENT_INVOKE
        else:
            required_capability = _QUERY_CAPABILITY
        if required_capability not in resolved.capabilities:
            raise ApiError(
                ErrorCode.CAPABILITY_DENIED,
                "The required capability is not granted.",
                http_status_code=403,
            )

        # Canary routing only applies after the binding above is authorized, and is
        # scoped to this specific consumer; everyone else gets the active release.
        release, _is_canary = select_release(scenario=scenario, consumer=consumer)
        if release is None:
            raise ApiError(
                ErrorCode.RELEASE_NOT_AVAILABLE,
                "No active release for this scenario.",
                http_status_code=503,
                retryable=True,
            )

        input_payload = self._prepare_input(release, input_payload)
        _validate_input(release, input_payload)

        if dispatch_kind == "workflow":
            return self._process_workflow(
                request=request,
                consumer=consumer,
                request_id=request_id,
                alias=alias,
                input_payload=input_payload,
                resolved=resolved,
                release=release,
            )

        if dispatch_kind == "agent":
            return self._process_agent(
                request=request,
                consumer=consumer,
                request_id=request_id,
                alias=alias,
                input_payload=input_payload,
                resolved=resolved,
                release=release,
            )

        # Idempotency: replay identical, conflict on differing body.
        idem_key = request.headers.get("Idempotency-Key")
        request_hash = compute_checksum(
            {"alias": alias, "input": input_payload, "op": self.operation}
        )
        if idem_key:
            replay = self._check_idempotency(consumer, idem_key, request_hash)
            if replay is not None:
                return replay

        context = issue_execution_context(
            organization_id=consumer.organization_id,
            project_id=scenario.project_id,
            scenario_id=scenario.id,
            scenario_alias=alias,
            consumer_id=consumer.id,
            capabilities=list(resolved.capabilities),
            release_id=release.id,
            request_id=request_id,
        )
        result = dispatch(
            execution_context=context,
            validated_input=input_payload,
            operation=self.operation,
            release=release,
        )

        body = {
            "request_id": request_id,
            "scenario_alias": alias,
            "release_id": release.id,
            "status": result["status"],
            "output": result["output"],
            "usage": result["usage"],
        }
        if idem_key:
            self._store_idempotency(consumer, idem_key, request_hash, 200, body)

        record_event(
            actor_type="consumer",
            actor_id=consumer.subject,
            action=f"gateway.{self.operation}",
            outcome="success",
            organization_id=consumer.organization_id,
            resource_type="scenario",
            resource_id=str(scenario.id),
            request_id=request_id,
        )
        self._record_usage_success(
            consumer, request_id, scenario, release, result["status"], result["usage"]
        )
        return Response(body, status=200)

    def _dispatch_kind(self, scenario: Any, input_payload: dict[str, Any]) -> str:
        del input_payload
        if self.operation == "invoke" and scenario.type == ScenarioType.WORKFLOW:
            return "workflow"
        if self.operation == "invoke" and scenario.type == ScenarioType.AGENT:
            return "agent"
        return "query"

    def _prepare_input(self, release: Any, input_payload: dict[str, Any]) -> dict[str, Any]:
        del release
        return input_payload

    def _process_workflow(
        self,
        *,
        request: Request,
        consumer: Any,
        request_id: str,
        alias: str,
        input_payload: dict[str, Any],
        resolved: Any,
        release: Any,
    ) -> Response:
        idempotency_key = request.headers.get("Idempotency-Key", "")
        request_hash = compute_checksum(
            {"alias": alias, "input": input_payload, "op": f"{self.operation}:workflow"}
        )
        if idempotency_key:
            replay = self._check_idempotency(consumer, idempotency_key, request_hash)
            if replay is not None:
                return replay
        try:
            workflow_version = resolve_release_workflow(release)
        except WorkflowCompileError as exc:
            raise ApiError(
                ErrorCode.RUNTIME_NOT_AVAILABLE,
                "The workflow runtime is not available for this release.",
                http_status_code=503,
                retryable=False,
            ) from exc
        scenario = resolved.binding.scenario
        context = issue_execution_context(
            organization_id=consumer.organization_id,
            project_id=scenario.project_id,
            scenario_id=scenario.id,
            scenario_alias=alias,
            consumer_id=consumer.id,
            capabilities=list(resolved.capabilities),
            release_id=release.id,
            request_id=request_id,
        )
        try:
            run, created = request_workflow_run(
                release=release,
                consumer=consumer,
                workflow_version=workflow_version,
                execution_context=context,
                input_payload=input_payload,
                idempotency_key=idempotency_key,
            )
        except WorkflowRequestError as exc:
            if exc.code == "IDEMPOTENCY_CONFLICT":
                raise ApiError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "Idempotency-Key was reused with a different workflow request.",
                    http_status_code=409,
                ) from exc
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "A bounded Idempotency-Key is required for workflow execution.",
                http_status_code=400,
            ) from exc
        if created:
            transaction.on_commit(lambda: execute_workflow_run.delay(run.id, run.organization_id))
        body = {
            "request_id": request_id,
            "scenario_alias": alias,
            "release_id": release.id,
            "run_id": str(run.id),
            "status": str(run.status),
        }
        if idempotency_key:
            self._store_idempotency(consumer, idempotency_key, request_hash, 202, body)
        record_event(
            actor_type="consumer",
            actor_id=consumer.subject,
            action="gateway.workflow_run",
            outcome="success",
            organization_id=consumer.organization_id,
            resource_type="workflow_run",
            resource_id=str(run.id),
            request_id=request_id,
        )
        UsageEvent.objects.create(
            request_id=request_id,
            organization_id=consumer.organization_id,
            scenario_id=scenario.id,
            release_id=release.id,
            consumer_id=consumer.id,
            operation="workflow_run",
            status="queued",
        )
        return Response(body, status=202)

    def _process_agent(
        self,
        *,
        request: Request,
        consumer: Any,
        request_id: str,
        alias: str,
        input_payload: dict[str, Any],
        resolved: Any,
        release: Any,
    ) -> Response:
        idempotency_key = request.headers.get("Idempotency-Key", "")
        request_hash = compute_checksum(
            {"alias": alias, "input": input_payload, "op": f"{self.operation}:agent"}
        )
        if idempotency_key:
            replay = self._check_idempotency(consumer, idempotency_key, request_hash)
            if replay is not None:
                return replay
        try:
            agent_version = resolve_release_agent(release)
        except AgentCompileError as exc:
            raise ApiError(
                ErrorCode.RUNTIME_NOT_AVAILABLE,
                "The agent runtime is not available for this release.",
                http_status_code=503,
                retryable=False,
            ) from exc
        scenario = resolved.binding.scenario
        context = issue_execution_context(
            organization_id=consumer.organization_id,
            project_id=scenario.project_id,
            scenario_id=scenario.id,
            scenario_alias=alias,
            consumer_id=consumer.id,
            capabilities=list(resolved.capabilities),
            release_id=release.id,
            request_id=request_id,
        )
        try:
            run, created = request_agent_run(
                release=release,
                consumer=consumer,
                agent_version=agent_version,
                execution_context=context,
                input_payload=input_payload,
                idempotency_key=idempotency_key,
            )
        except AgentRequestError as exc:
            if exc.code == "IDEMPOTENCY_CONFLICT":
                raise ApiError(
                    ErrorCode.IDEMPOTENCY_CONFLICT,
                    "Idempotency-Key was reused with a different agent request.",
                    http_status_code=409,
                ) from exc
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "A bounded Idempotency-Key is required for agent execution.",
                http_status_code=400,
            ) from exc
        if created:
            transaction.on_commit(lambda: execute_agent_run.delay(run.id, run.organization_id))
        body = {
            "request_id": request_id,
            "scenario_alias": alias,
            "release_id": release.id,
            "run_id": str(run.public_id),
            "status": str(run.status),
        }
        if idempotency_key:
            self._store_idempotency(consumer, idempotency_key, request_hash, 202, body)
        record_event(
            actor_type="consumer",
            actor_id=consumer.subject,
            action="gateway.agent_run",
            outcome="success",
            organization_id=consumer.organization_id,
            resource_type="agent_run",
            resource_id=str(run.public_id),
            request_id=request_id,
        )
        UsageEvent.objects.create(
            request_id=request_id,
            organization_id=consumer.organization_id,
            scenario_id=scenario.id,
            release_id=release.id,
            consumer_id=consumer.id,
            operation="agent_run",
            status="queued",
        )
        return Response(body, status=202)

    def _check_idempotency(self, consumer: Any, key: str, request_hash: str) -> Response | None:
        existing = IdempotencyRecord.objects.filter(consumer=consumer, key=key).first()
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency-Key was reused with a different request body.",
                http_status_code=409,
            )
        return Response(existing.response_body, status=existing.response_status)

    def _store_idempotency(
        self, consumer: Any, key: str, request_hash: str, status_code: int, body: dict
    ) -> None:
        try:
            IdempotencyRecord.objects.create(
                consumer=consumer,
                key=key,
                request_hash=request_hash,
                response_status=status_code,
                response_body=body,
            )
        except IntegrityError:
            # Concurrent create with the same key; the stored one wins.
            pass

    def _record_usage_success(
        self,
        consumer: Any,
        request_id: str,
        scenario: Any,
        release: Any,
        status: str,
        usage: dict[str, int],
    ) -> None:
        UsageEvent.objects.create(
            request_id=request_id,
            organization_id=consumer.organization_id,
            scenario_id=scenario.id,
            release_id=release.id,
            consumer_id=consumer.id,
            operation=self.operation,
            status=status,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    def _record_usage(
        self, consumer: Any, request_id: str, alias: str, error_code: str, started: float
    ) -> None:
        UsageEvent.objects.create(
            request_id=request_id,
            organization_id=consumer.organization_id,
            consumer_id=consumer.id,
            operation=self.operation,
            status="error",
            error_code=error_code,
            latency_ms=int((time.monotonic() - started) * 1000),
        )


class InvokeView(_GatewayView):
    operation = "invoke"


class QueryView(_GatewayView):
    """RAG facade: top-level ``query`` is reshaped into the invoke input."""

    operation = "query"

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        alias = _require_alias(data)
        query = data.get("query")
        if not isinstance(query, str) or not query:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "query is required.", http_status_code=400)
        payload: dict[str, Any] = {"query": query}
        if isinstance(data.get("conversation_id"), str):
            payload["conversation_id"] = data["conversation_id"]
        return alias, payload


class _OpenAICompatibilityView(_GatewayView):
    """Shared compatible envelope/error behavior over the governed gateway."""

    _requested_alias = ""

    def post(self, request: Request) -> Response:
        if not settings.OPENAI_COMPAT_ENABLED:
            raise ApiError(
                ErrorCode.RUNTIME_NOT_AVAILABLE,
                "The compatibility endpoint is not enabled.",
                http_status_code=404,
            )
        response = super().post(request)
        body = dict(response.data)
        body["_http_status"] = response.status_code
        return Response(self._adapt_success(body), status=response.status_code)

    def handle_exception(self, exc: Exception) -> Response:
        response = super().handle_exception(exc)
        response.data = compatible_error(response.data)
        return response

    def _prepare_input(self, release: Any, input_payload: dict[str, Any]) -> dict[str, Any]:
        return prepare_runtime_input(release, input_payload)

    def _adapt_success(self, body: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class ChatCompletionsView(_OpenAICompatibilityView):
    operation = "openai.chat_completions"

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        alias, payload = parse_chat_request(data)
        self._requested_alias = alias
        return alias, payload

    def _dispatch_kind(self, scenario: Any, input_payload: dict[str, Any]) -> str:
        del input_payload
        if scenario.type != ScenarioType.RAG:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "Chat Completions supports synchronous RAG scenarios only.",
                http_status_code=400,
                details=[{"path": ["model"]}],
            )
        return "query"

    def _adapt_success(self, body: dict[str, Any]) -> dict[str, Any]:
        return chat_response(body, str(self._requested_alias))


class ResponsesView(_OpenAICompatibilityView):
    operation = "openai.responses"

    def _extract(self, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        alias, payload = parse_responses_request(data)
        self._requested_alias = alias
        return alias, payload

    def _dispatch_kind(self, scenario: Any, input_payload: dict[str, Any]) -> str:
        background = input_payload.get("__openai_background", False)
        if scenario.type == ScenarioType.WORKFLOW:
            if background is not True:
                self._background_required()
            return "workflow"
        if scenario.type == ScenarioType.AGENT:
            if background is not True:
                self._background_required()
            return "agent"
        if background is True:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR,
                "background is only supported for workflow and agent scenarios.",
                http_status_code=400,
                details=[{"path": ["background"]}],
            )
        return "query"

    def _adapt_success(self, body: dict[str, Any]) -> dict[str, Any]:
        return responses_response(body, str(self._requested_alias))

    @staticmethod
    def _background_required() -> None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "background=true is required for workflow and agent scenarios.",
            http_status_code=400,
            details=[{"path": ["background"]}],
        )


class RunStatusView(APIView):
    """Consumer/tenant-scoped run status + cancel for both workflow and agent runs.

    A numeric ``run_id`` addresses a workflow run (legacy Sprint 8 contract); a UUID
    addresses an agent run by its opaque ``public_id``. The two id spaces are disjoint,
    so the shared surface never leaks or collides across the two runtimes.
    """

    def get(self, request: Request, run_id: str) -> Response:
        if run_id.isdigit():
            return self._workflow_status(self._resolve_workflow(request, run_id))
        return self._agent_status(self._resolve_agent(request, run_id))

    def delete(self, request: Request, run_id: str) -> Response:
        if run_id.isdigit():
            run = self._resolve_workflow(request, run_id)
            cancelled = cancel_workflow_run(run=run, consumer=request.auth)
            return Response({"run_id": str(cancelled.id), "status": str(cancelled.status)})
        agent_run = self._resolve_agent(request, run_id)
        cancelled_agent = cancel_agent_run(run=agent_run, consumer=request.auth)
        return Response(
            {"run_id": str(cancelled_agent.public_id), "status": str(cancelled_agent.status)}
        )

    @staticmethod
    def _workflow_status(run: WorkflowRun) -> Response:
        body: dict[str, Any] = {
            "run_id": str(run.id),
            "status": str(run.status),
            "release_id": run.release_id,
            "error_code": run.error_code,
        }
        output = run.redacted_state.get("output")
        if run.status == WorkflowRunStatus.COMPLETED and isinstance(output, dict):
            body["output"] = output
        return Response(body)

    @staticmethod
    def _agent_status(run: AgentRun) -> Response:
        body: dict[str, Any] = {
            "run_id": str(run.public_id),
            "status": str(run.status),
            "release_id": run.release_id,
            "error_code": run.error_code,
        }
        if run.status == AgentRunStatus.COMPLETED:
            output_key = run.agent_version.compiled_config.get("output_key", "output")
            output = run.checkpoint.get(output_key)
            if isinstance(output, dict):
                body["output"] = output
        return Response(body)

    @staticmethod
    def _resolve_workflow(request: Request, run_id: str) -> WorkflowRun:
        run = WorkflowRun.objects.filter(
            pk=int(run_id),
            consumer=request.auth,
            organization_id=request.auth.organization_id,
        ).first()
        if run is None:
            raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)
        return run

    @staticmethod
    def _resolve_agent(request: Request, run_id: str) -> AgentRun:
        try:
            public_id = uuid.UUID(run_id)
        except ValueError:
            raise ApiError(
                ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404
            ) from None
        run = (
            AgentRun.objects.select_related("agent_version")
            .filter(
                public_id=public_id,
                consumer=request.auth,
                organization_id=request.auth.organization_id,
            )
            .first()
        )
        if run is None:
            raise ApiError(ErrorCode.RUN_NOT_FOUND, "Run not found.", http_status_code=404)
        return run
