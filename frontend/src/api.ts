// Typed, same-origin client for the operator builder API. Every write carries the Django
// CSRF token from the cookie; the browser's session cookie authenticates the operator.
// There is no token/bearer path and no cross-origin request — the SPA is served by Django.

import type {
  AcceptedCandidateDraft,
  AiCandidateResult,
  CapabilityMissingResult,
  AiCandidateType,
  ArtifactDraft,
  ArtifactPublishResult,
  ArtifactVersionPreview,
  Draft,
  DiagnosticsResult,
  ManifestCompileResult,
  ManifestOptionsResult,
  ManifestPreflightResult,
  ManifestRequirementsResult,
  ManifestSelectionPayload,
  ModelProfileOption,
  GenerateNodeBinding,
  RetrieveNodeBinding,
  NodeSchema,
} from "./types";

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message || code);
    this.code = code;
    this.status = status;
  }
}

export function getCookie(name: string): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : "";
}

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET" && method !== "HEAD") {
    headers["Content-Type"] = "application/json";
    headers["X-CSRFToken"] = getCookie("csrftoken");
  }
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: { ...headers, ...(options.headers as Record<string, string>) },
  });
  const text = await response.text();
  let data: unknown = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      throw new ApiError(
        response.status,
        "unexpected_response",
        response.ok
          ? "Sunucu JSON olmayan beklenmedik bir yanıt döndürdü."
          : `Sunucu isteği JSON olmayan bir yanıtla reddetti (HTTP ${response.status}).`,
      );
    }
  }
  if (!response.ok) {
    const envelope = data && typeof data === "object" ? data as { error?: unknown } : {};
    const err = envelope.error && typeof envelope.error === "object"
      ? envelope.error as { code?: string; message?: string }
      : {};
    throw new ApiError(response.status, err.code ?? "error", err.message ?? "");
  }
  return data as T;
}

export class BuilderApi {
  constructor(private base: string) {}

  private url(path: string): string {
    return this.base.replace(/\/$/, "") + path;
  }

  nodeSchema(organization: string): Promise<NodeSchema> {
    return request<NodeSchema>(this.url(`/node-schema/?organization=${encodeURIComponent(organization)}`));
  }

  listDrafts(): Promise<{ drafts: Draft[] }> {
    return request(this.url("/drafts/"));
  }

  generateCandidate(payload: {
    organization: string; project_id: number; description: string; artifact_type: AiCandidateType;
    scenario_id?: number;
  }): Promise<AiCandidateResult | CapabilityMissingResult> {
    return request(this.url("/ai-candidates/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  repairCandidate(payload: {
    organization: string;
    project_id: number;
    scenario_id: number;
    candidate: Record<string, unknown>;
    instruction?: string;
    prompt_contract?: AiCandidateResult["prompt_contract"];
    authoring_context?: AiCandidateResult["authoring_context"];
  }): Promise<AiCandidateResult | CapabilityMissingResult> {
    return request(this.url("/ai-candidates/repair/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  acceptCandidate(payload: {
    organization: string; project_id: number; name: string; logical_id?: string;
    scenario_id?: number;
    artifact_type: AiCandidateType; candidate: Record<string, unknown>;
    prompt_contract: AiCandidateResult["prompt_contract"];
    authoring_context?: AiCandidateResult["authoring_context"];
    draft_id?: number; revision?: number;
  }): Promise<AcceptedCandidateDraft> {
    return request(this.url("/ai-candidates/accept/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  transientDiagnostics(payload: { organization: string; body: Record<string, unknown> }): Promise<DiagnosticsResult> {
    return request(this.url("/transient-diagnostics/"), {
      method: "POST", body: JSON.stringify(payload),
    });
  }

  manifestOptions(
    optionsUrl: string,
    params: { artifact_type?: string; logical_id?: string; preset?: string } = {},
  ): Promise<ManifestOptionsResult> {
    const url = new URL(optionsUrl, window.location.origin);
    if (params.artifact_type) url.searchParams.set("artifact_type", params.artifact_type);
    if (params.logical_id) url.searchParams.set("logical_id", params.logical_id);
    if (params.preset) url.searchParams.set("preset", params.preset);
    return request<ManifestOptionsResult>(url.toString());
  }

  preflightManifest(
    scenarioPublicId: string,
    items: ManifestSelectionPayload[],
  ): Promise<ManifestPreflightResult> {
    return request(this.url(`/scenarios/${encodeURIComponent(scenarioPublicId)}/release-manifest/preflight/`), {
      method: "POST",
      body: JSON.stringify({ items }),
    });
  }

  manifestRequirements(
    scenarioPublicId: string,
    workflowArtifactId: number,
  ): Promise<ManifestRequirementsResult> {
    return request(this.url(`/scenarios/${encodeURIComponent(scenarioPublicId)}/release-manifest/requirements/`), {
      method: "POST",
      body: JSON.stringify({ workflow_artifact_id: workflowArtifactId }),
    });
  }

  compileManifest(
    scenarioPublicId: string,
    items: ManifestSelectionPayload[],
  ): Promise<ManifestCompileResult> {
    return request(this.url(`/scenarios/${encodeURIComponent(scenarioPublicId)}/release-manifest/compile/`), {
      method: "POST",
      body: JSON.stringify({ items }),
    });
  }

  listArtifactDrafts(): Promise<{ drafts: ArtifactDraft[] }> {
    return request(this.url("/artifact-drafts/"));
  }

  createArtifactDraft(payload: {
    organization: string;
    project_id: number;
    scenario_id: number;
    artifact_type?: "prompt_template" | "model_profile" | "retrieval_profile";
    name?: string;
    logical_id?: string;
    logical_description?: string;
    body?: Record<string, unknown>;
    source_artifact_version_id?: number;
  }): Promise<ArtifactDraft> {
    return request(this.url("/artifact-drafts/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  modelProfileOptions(params: {
    organization: string;
    projectId: number;
    scenarioId: number;
    selectedProfileId?: string;
  }): Promise<{ options: ModelProfileOption[]; limited: boolean }> {
    const query = new URLSearchParams({
      organization: params.organization,
      project_id: String(params.projectId),
      scenario_id: String(params.scenarioId),
    });
    if (params.selectedProfileId) query.set("selected_profile_id", params.selectedProfileId);
    return request(this.url(`/model-profile-options/?${query.toString()}`));
  }

  getArtifactDraft(id: number): Promise<ArtifactDraft> {
    return request(this.url(`/artifact-drafts/${id}/`));
  }

  updateArtifactDraft(
    id: number, payload: { revision: number; name?: string; body?: Record<string, unknown> },
  ): Promise<ArtifactDraft> {
    return request(this.url(`/artifact-drafts/${id}/`), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  deleteArtifactDraft(id: number, revision: number): Promise<{ deleted: boolean }> {
    return request(this.url(`/artifact-drafts/${id}/`), {
      method: "DELETE", body: JSON.stringify({ revision }),
    });
  }

  artifactDraftDiagnostics(
    id: number, body: Record<string, unknown>,
  ): Promise<DiagnosticsResult> {
    return request(this.url(`/artifact-drafts/${id}/diagnostics/`), {
      method: "POST",
      body: JSON.stringify({ body }),
    });
  }

  publishArtifactDraft(
    id: number, revision: number, versionDescription: string,
  ): Promise<ArtifactPublishResult> {
    return request(this.url(`/artifact-drafts/${id}/publish/`), {
      method: "POST",
      body: JSON.stringify({ revision, version_description: versionDescription }),
    });
  }

  artifactVersionPreview(
    scenarioPublicId: string, artifactVersionId: number,
  ): Promise<ArtifactVersionPreview> {
    return request(this.url(
      `/scenarios/${encodeURIComponent(scenarioPublicId)}/artifact-versions/${artifactVersionId}/`,
    ));
  }

  getDraft(id: number): Promise<Draft> {
    return request<Draft>(this.url(`/drafts/${id}/`));
  }

  generateNodeBinding(draftId: number, nodeId: string): Promise<GenerateNodeBinding> {
    return request(this.url(
      `/drafts/${draftId}/generate-nodes/${encodeURIComponent(nodeId)}/binding/`,
    ));
  }

  saveGenerateNodeBinding(
    draftId: number,
    nodeId: string,
    payload: {
      revision: number;
      workflow_body: Record<string, unknown>;
      prompt_text: string;
      model_profile_id: string;
    },
  ): Promise<{ draft: Draft; binding: GenerateNodeBinding }> {
    return request(this.url(
      `/drafts/${draftId}/generate-nodes/${encodeURIComponent(nodeId)}/binding/`,
    ), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  retrieveNodeBinding(draftId: number, nodeId: string): Promise<RetrieveNodeBinding> {
    return request(this.url(
      `/drafts/${draftId}/retrieve-nodes/${encodeURIComponent(nodeId)}/binding/`,
    ));
  }

  saveRetrieveNodeBinding(
    draftId: number,
    nodeId: string,
    payload: {
      revision: number;
      workflow_body: Record<string, unknown>;
      profile_body: Record<string, unknown>;
    },
  ): Promise<{ draft: Draft; binding: RetrieveNodeBinding }> {
    return request(this.url(
      `/drafts/${draftId}/retrieve-nodes/${encodeURIComponent(nodeId)}/binding/`,
    ), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  createDraft(payload: {
    organization: string;
    project_id?: number;
    scenario_id?: number;
    name: string;
    logical_id: string;
    logical_description?: string;
    body: Record<string, unknown>;
  }): Promise<Draft> {
    return request<Draft>(this.url("/drafts/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateDraft(
    id: number, payload: { revision: number; name?: string; body?: Record<string, unknown> },
  ): Promise<Draft> {
    return request<Draft>(this.url(`/drafts/${id}/`), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  deleteDraft(id: number, revision: number): Promise<{ deleted: boolean }> {
    return request(this.url(`/drafts/${id}/`), {
      method: "DELETE", body: JSON.stringify({ revision }),
    });
  }

  diagnostics(id: number, body: Record<string, unknown>): Promise<DiagnosticsResult> {
    return request<DiagnosticsResult>(this.url(`/drafts/${id}/diagnostics/`), {
      method: "POST",
      body: JSON.stringify({ body }),
    });
  }

  publish(id: number, revision: number, versionDescription = ""): Promise<{
    published: boolean;
    artifact_type: string;
    logical_id: string;
    logical_description: string;
    version: number;
    version_description: string;
    checksum: string;
    revision: number;
  }> {
    return request(this.url(`/drafts/${id}/publish/`), {
      method: "POST", body: JSON.stringify({ revision, version_description: versionDescription }),
    });
  }
}
