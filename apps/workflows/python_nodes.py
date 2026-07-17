"""Fail-closed reviewed Python-node execution seam (P2.6.8).

Static policy is defense in depth. Only an approved production runner satisfying ADR-0011 may be
activated; the bundled subprocess runner is an isolated-process test harness, not that boundary.
"""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from django.conf import settings
from django.utils.module_loading import import_string

from apps.workflows.state_mapping import MappingError, apply_output_mapping, compile_mappings

RULESET_ID = "agenthub-python-node-v1"
ALLOWED_MODULES = frozenset({"decimal", "fractions", "math", "statistics"})
MAX_SOURCE_BYTES = 32_768
MAX_OUTPUT_BYTES = 262_144
MAX_MEMORY_BYTES = 64 * 1024 * 1024
MAX_WALL_SECONDS = 5.0
MAX_RUNNER_RESPONSE_BYTES = MAX_OUTPUT_BYTES + 4096

_FORBIDDEN_CALLS = frozenset(
    {
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "getattr",
        "globals",
        "hasattr",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
        "__import__",
    }
)


class PythonNodeError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SecurityFinding:
    code: str
    line: int
    column: int


@dataclass(frozen=True)
class SecurityReview:
    ruleset_id: str
    ruleset_checksum: str
    source_checksum: str
    findings: tuple[SecurityFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings


@dataclass(frozen=True)
class PythonNodePin:
    organization_id: int
    node_ref: str
    revision: int
    source_checksum: str
    contract_checksum: str


@dataclass(frozen=True)
class ResolvedPythonNode:
    pin: PythonNodePin
    source: str
    config_schema: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    requested_modules: frozenset[str]
    approved: bool
    active: bool
    rejected: bool = False


class PythonNodeResolver(Protocol):
    def resolve(self, pin: PythonNodePin) -> ResolvedPythonNode | None: ...


class PythonNodeRunner(Protocol):
    is_production_isolated: bool

    def execute(
        self,
        *,
        source: str,
        config: dict[str, Any],
        input_payload: dict[str, Any],
        wall_seconds: float,
        memory_bytes: int,
        output_bytes: int,
        idempotency_key: str,
        requested_modules: frozenset[str],
    ) -> dict[str, Any]: ...


AuditSink = Callable[[dict[str, str | int | bool]], None]


class DisabledPythonNodeRunner:
    """Production-safe default: execution cannot silently fall back in-process."""

    is_production_isolated = False

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        raise PythonNodeError("PYTHON_NODE_RUNNER_DISABLED")


class SubprocessTestRunner:
    """Dependency-free separate-process harness; explicitly not production isolation."""

    is_production_isolated = False

    def execute(
        self,
        *,
        source: str,
        config: dict[str, Any],
        input_payload: dict[str, Any],
        wall_seconds: float,
        memory_bytes: int,
        output_bytes: int,
        idempotency_key: str,
        requested_modules: frozenset[str],
    ) -> dict[str, Any]:
        del idempotency_key  # execution authority/idempotency remain in the parent contract
        worker = Path(__file__).with_name("python_node_worker.py")
        request = json.dumps(
            {
                "source": source,
                "config": config,
                "input": input_payload,
                "memory_bytes": memory_bytes,
                "output_bytes": output_bytes,
                "requested_modules": sorted(requested_modules),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            completed = subprocess.run(  # noqa: S603
                [sys.executable, "-I", str(worker)],
                input=request,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=wall_seconds,
                check=False,
                env={"PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"},
            )
        except subprocess.TimeoutExpired:
            raise PythonNodeError("PYTHON_NODE_TIMEOUT") from None
        if len(completed.stdout) > output_bytes + 256:
            raise PythonNodeError("PYTHON_NODE_OUTPUT_LIMIT")
        try:
            response = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PythonNodeError("PYTHON_NODE_PROTOCOL_INVALID") from None
        if completed.returncode != 0 or not isinstance(response, dict):
            raise PythonNodeError("PYTHON_NODE_RUNNER_FAILED")
        if response.get("status") != "ok":
            code = response.get("code")
            allowed = {
                "PYTHON_NODE_ENTRYPOINT_INVALID",
                "PYTHON_NODE_EXECUTION_FAILED",
                "PYTHON_NODE_MEMORY_LIMIT",
                "PYTHON_NODE_OUTPUT_LIMIT",
            }
            raise PythonNodeError(code if code in allowed else "PYTHON_NODE_RUNNER_FAILED")
        output = response.get("output")
        if not isinstance(output, dict):
            raise PythonNodeError("PYTHON_NODE_OUTPUT_INVALID")
        return output


class OpenShiftPythonNodeRunner:
    """Bounded client for the dedicated, credentials-free OpenShift runner Service.

    Deployment isolation is an environment attestation, not a property Python can infer. The
    adapter therefore remains non-production until an operator explicitly attests the target SCC,
    NetworkPolicy, service-mesh transport and resource-limit evidence.
    """

    def __init__(self) -> None:
        self.endpoint = str(settings.PYTHON_NODE_RUNNER_URL).rstrip("/")
        self.is_production_isolated = bool(settings.PYTHON_NODE_RUNNER_ATTESTED)
        parsed = urllib.parse.urlsplit(self.endpoint)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            self.endpoint = ""

    def execute(
        self,
        *,
        source: str,
        config: dict[str, Any],
        input_payload: dict[str, Any],
        wall_seconds: float,
        memory_bytes: int,
        output_bytes: int,
        idempotency_key: str,
        requested_modules: frozenset[str],
    ) -> dict[str, Any]:
        if not self.endpoint or not self.is_production_isolated:
            raise PythonNodeError("PYTHON_NODE_RUNNER_NOT_ATTESTED")
        idempotency_checksum = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        body = json.dumps(
            {
                "protocol_version": "python-node-runner/v1",
                "idempotency_key": idempotency_key,
                "expires_at_unix_ms": int((time.time() + wall_seconds + 2.0) * 1000),
                "source": source,
                "config": config,
                "input": input_payload,
                "wall_milliseconds": max(1, int(wall_seconds * 1000)),
                "memory_bytes": memory_bytes,
                "output_bytes": output_bytes,
                "requested_modules": sorted(requested_modules),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > MAX_SOURCE_BYTES + MAX_OUTPUT_BYTES:
            raise PythonNodeError("PYTHON_NODE_REQUEST_TOO_LARGE")
        request = urllib.request.Request(  # noqa: S310 - operator-owned internal Service URL
            f"{self.endpoint}/v1/execute",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirectHandler()
            )
            with opener.open(request, timeout=wall_seconds + 1.0) as response:
                raw = response.read(MAX_RUNNER_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise PythonNodeError("PYTHON_NODE_RUNNER_CAPACITY") from None
            raise PythonNodeError("PYTHON_NODE_RUNNER_FAILED") from None
        except (urllib.error.URLError, TimeoutError):
            raise PythonNodeError("PYTHON_NODE_OUTCOME_UNKNOWN") from None
        if len(raw) > MAX_RUNNER_RESPONSE_BYTES:
            raise PythonNodeError("PYTHON_NODE_OUTPUT_LIMIT")
        try:
            response_body = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PythonNodeError("PYTHON_NODE_PROTOCOL_INVALID") from None
        if not isinstance(response_body, dict):
            raise PythonNodeError("PYTHON_NODE_PROTOCOL_INVALID")
        if response_body.get("idempotency_checksum") != idempotency_checksum:
            raise PythonNodeError("PYTHON_NODE_RESPONSE_BINDING_INVALID")
        if response_body.get("status") != "ok":
            code = response_body.get("code")
            allowed = {
                "PYTHON_NODE_ENTRYPOINT_INVALID",
                "PYTHON_NODE_EXECUTION_FAILED",
                "PYTHON_NODE_MEMORY_LIMIT",
                "PYTHON_NODE_OUTPUT_LIMIT",
                "PYTHON_NODE_TIMEOUT",
            }
            raise PythonNodeError(code if code in allowed else "PYTHON_NODE_RUNNER_FAILED")
        output = response_body.get("output")
        if not isinstance(output, dict):
            raise PythonNodeError("PYTHON_NODE_OUTPUT_INVALID")
        return output


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None


def review_source(source: str, requested_modules: frozenset[str]) -> SecurityReview:
    encoded = source.encode("utf-8")
    source_checksum = hashlib.sha256(encoded).hexdigest()
    findings: list[SecurityFinding] = []
    if len(encoded) > MAX_SOURCE_BYTES:
        findings.append(SecurityFinding("SOURCE_TOO_LARGE", 0, 0))
    unknown_modules = requested_modules - ALLOWED_MODULES
    if unknown_modules:
        findings.append(SecurityFinding("MODULE_NOT_ALLOWED", 0, 0))
    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        findings.append(SecurityFinding("SYNTAX_INVALID", exc.lineno or 0, exc.offset or 0))
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [alias.name.split(".", 1)[0] for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [(node.module or "").split(".", 1)[0]]
                )
                if any(
                    name not in requested_modules or name not in ALLOWED_MODULES for name in names
                ):
                    findings.append(_finding("IMPORT_FORBIDDEN", node))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in _FORBIDDEN_CALLS:
                    findings.append(_finding("CALL_FORBIDDEN", node))
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                findings.append(_finding("REFLECTION_FORBIDDEN", node))
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                findings.append(_finding("REFLECTION_FORBIDDEN", node))
    rules = json.dumps(
        {"id": RULESET_ID, "modules": sorted(ALLOWED_MODULES), "calls": sorted(_FORBIDDEN_CALLS)},
        separators=(",", ":"),
    ).encode("utf-8")
    return SecurityReview(
        ruleset_id=RULESET_ID,
        ruleset_checksum=hashlib.sha256(rules).hexdigest(),
        source_checksum=source_checksum,
        findings=tuple(sorted(set(findings), key=lambda item: (item.line, item.column, item.code))),
    )


def execute_reviewed_python_node(
    *,
    pin: PythonNodePin,
    resolver: PythonNodeResolver,
    runner: PythonNodeRunner,
    config: dict[str, Any],
    input_payload: dict[str, Any],
    output_mapping: list[dict[str, str]] | None,
    state: dict[str, Any],
    idempotency_key: str,
    audit: AuditSink,
) -> dict[str, Any]:
    metadata: dict[str, str | int | bool] = {
        "event": "python_node.execute",
        "organization_id": pin.organization_id,
        "node_ref": pin.node_ref,
        "revision": pin.revision,
        "source_checksum": pin.source_checksum,
        "outcome": "denied",
    }
    try:
        resolved = _resolve_exact(pin, resolver)
        review = review_source(resolved.source, resolved.requested_modules)
        if not review.passed or review.source_checksum != pin.source_checksum:
            raise PythonNodeError("PYTHON_NODE_SECURITY_REVIEW_BLOCKED")
        _validate(config, resolved.config_schema, "PYTHON_NODE_CONFIG_INVALID")
        _validate(input_payload, resolved.input_schema, "PYTHON_NODE_INPUT_INVALID")
        if output_mapping is not None:
            compile_mappings(output_mapping, restrict_destination=True)
        output = runner.execute(
            source=resolved.source,
            config=config,
            input_payload=input_payload,
            wall_seconds=MAX_WALL_SECONDS,
            memory_bytes=MAX_MEMORY_BYTES,
            output_bytes=MAX_OUTPUT_BYTES,
            idempotency_key=idempotency_key,
            requested_modules=resolved.requested_modules,
        )
        _validate(output, resolved.output_schema, "PYTHON_NODE_OUTPUT_INVALID")
        _resolve_exact(pin, resolver)  # disable/checksum/tenant race: reject late result
        if output_mapping is None:
            updated = output
        else:
            try:
                updated = apply_output_mapping(state, output, output_mapping)
            except MappingError as exc:
                raise PythonNodeError(exc.code) from None
        metadata["outcome"] = "completed"
        metadata["reason_code"] = "PYTHON_NODE_OK"
        audit(metadata)
        return updated
    except PythonNodeError as exc:
        metadata["reason_code"] = exc.code
        audit(metadata)
        raise


def execute_configured_python_node(
    *, config: dict[str, Any], input_payload: dict[str, Any], run: Any, node_id: str
) -> dict[str, Any]:
    """Canonical workflow adapter; no configured/approved backend means deny."""
    if not settings.PYTHON_NODE_RUNTIME_ENABLED:
        raise PythonNodeError("PYTHON_NODE_RUNTIME_DISABLED")
    resolver_path = str(settings.PYTHON_NODE_RESOLVER)
    runner_path = str(settings.PYTHON_NODE_RUNNER)
    if not resolver_path or not runner_path:
        raise PythonNodeError("PYTHON_NODE_RUNNER_DISABLED")
    resolver = import_string(resolver_path)()
    runner = import_string(runner_path)()
    if not getattr(runner, "is_production_isolated", False):
        # The bundled harness or an unreviewed adapter can never be selected for activation.
        raise PythonNodeError("PYTHON_NODE_RUNNER_NOT_PRODUCTION_SAFE")
    pin = PythonNodePin(
        organization_id=run.organization_id,
        node_ref=str(config["node_ref"]),
        revision=int(config["revision"]),
        source_checksum=str(config["source_checksum"]),
        contract_checksum=str(config["contract_checksum"]),
    )
    audit_events: list[dict[str, str | int | bool]] = []
    try:
        # The workflow runtime applies the compiler-validated output_mapping atomically after this
        # adapter returns the schema-validated output envelope.
        result = execute_reviewed_python_node(
            pin=pin,
            resolver=resolver,
            runner=runner,
            config=dict(config["parameters"]),
            input_payload=input_payload,
            output_mapping=None,
            state={},
            idempotency_key=f"wf:{run.id}:{node_id}:{pin.source_checksum}",
            audit=audit_events.append,
        )
        return result
    finally:
        # Workflow task logging persists only stable metadata; source/raw payloads never enter it.
        for event in audit_events:
            _emit_safe_audit(run, event, node_id)


def _emit_safe_audit(run: Any, event: dict[str, str | int | bool], node_id: str) -> None:
    from apps.workflows.models import WorkflowRunEvent
    from apps.workflows.services import _next_sequence

    if not getattr(run, "id", 0):
        return
    WorkflowRunEvent.objects.create(
        run=run,
        organization_id=run.organization_id,
        sequence=_next_sequence(run),
        event_type="python_node_execution",
        node_id=node_id,
        outcome=str(event.get("outcome", "denied")),
        reason_code=str(event.get("reason_code", "PYTHON_NODE_AUDIT_INCOMPLETE")),
    )


def _resolve_exact(pin: PythonNodePin, resolver: PythonNodeResolver) -> ResolvedPythonNode:
    resolved = resolver.resolve(pin)
    if resolved is None or resolved.pin.organization_id != pin.organization_id:
        raise PythonNodeError("PYTHON_NODE_NOT_ALLOWED")
    if resolved.pin != pin:
        raise PythonNodeError("PYTHON_NODE_PIN_STALE")
    if resolved.rejected:
        raise PythonNodeError("PYTHON_NODE_REJECTED")
    if not resolved.approved:
        raise PythonNodeError("PYTHON_NODE_NOT_APPROVED")
    if not resolved.active:
        raise PythonNodeError("PYTHON_NODE_DISABLED")
    actual = hashlib.sha256(resolved.source.encode("utf-8")).hexdigest()
    if actual != pin.source_checksum:
        raise PythonNodeError("PYTHON_NODE_CHECKSUM_MISMATCH")
    contract = _contract_checksum(resolved)
    if contract != pin.contract_checksum:
        raise PythonNodeError("PYTHON_NODE_CONTRACT_MISMATCH")
    return resolved


def contract_checksum(
    config_schema: dict[str, Any],
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    requested_modules: frozenset[str] = frozenset(),
) -> str:
    value = {
        "config": config_schema,
        "input": input_schema,
        "output": output_schema,
        "requested_modules": sorted(requested_modules),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _contract_checksum(node: ResolvedPythonNode) -> str:
    return contract_checksum(
        node.config_schema, node.input_schema, node.output_schema, node.requested_modules
    )


def _validate(value: Any, schema: dict[str, Any], code: str) -> None:
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(value, schema)
    except jsonschema.SchemaError:
        raise PythonNodeError("PYTHON_NODE_SCHEMA_INVALID") from None
    except jsonschema.ValidationError:
        raise PythonNodeError(code) from None


def _finding(code: str, node: ast.AST) -> SecurityFinding:
    return SecurityFinding(code, getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
