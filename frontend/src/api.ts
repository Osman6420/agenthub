// Typed, same-origin client for the operator builder API. Every write carries the Django
// CSRF token from the cookie; the browser's session cookie authenticates the operator.
// There is no token/bearer path and no cross-origin request — the SPA is served by Django.

import type {
  AcceptedCandidateDraft,
  AiCandidateResult,
  AiCandidateType,
  ArtifactDraft,
  Draft,
  DiagnosticsResult,
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
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const err = (data && data.error) || {};
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
  }): Promise<AiCandidateResult> {
    return request(this.url("/ai-candidates/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  acceptCandidate(payload: {
    organization: string; project_id: number; name: string; logical_id: string;
    artifact_type: AiCandidateType; candidate: Record<string, unknown>;
    prompt_contract: AiCandidateResult["prompt_contract"];
  }): Promise<AcceptedCandidateDraft> {
    return request(this.url("/ai-candidates/accept/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  listArtifactDrafts(): Promise<{ drafts: ArtifactDraft[] }> {
    return request(this.url("/artifact-drafts/"));
  }

  getArtifactDraft(id: number): Promise<ArtifactDraft> {
    return request(this.url(`/artifact-drafts/${id}/`));
  }

  updateArtifactDraft(
    id: number, payload: { name?: string; body?: Record<string, unknown> },
  ): Promise<ArtifactDraft> {
    return request(this.url(`/artifact-drafts/${id}/`), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  deleteArtifactDraft(id: number): Promise<{ deleted: boolean }> {
    return request(this.url(`/artifact-drafts/${id}/`), { method: "DELETE" });
  }

  artifactDraftDiagnostics(
    id: number, body: Record<string, unknown>,
  ): Promise<DiagnosticsResult> {
    return request(this.url(`/artifact-drafts/${id}/diagnostics/`), {
      method: "POST",
      body: JSON.stringify({ body }),
    });
  }

  getDraft(id: number): Promise<Draft> {
    return request<Draft>(this.url(`/drafts/${id}/`));
  }

  createDraft(payload: {
    organization: string;
    name: string;
    logical_id: string;
    body: Record<string, unknown>;
  }): Promise<Draft> {
    return request<Draft>(this.url("/drafts/"), {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateDraft(id: number, payload: { name?: string; body?: Record<string, unknown> }): Promise<Draft> {
    return request<Draft>(this.url(`/drafts/${id}/`), {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  }

  deleteDraft(id: number): Promise<{ deleted: boolean }> {
    return request(this.url(`/drafts/${id}/`), { method: "DELETE" });
  }

  diagnostics(id: number, body: Record<string, unknown>): Promise<DiagnosticsResult> {
    return request<DiagnosticsResult>(this.url(`/drafts/${id}/diagnostics/`), {
      method: "POST",
      body: JSON.stringify({ body }),
    });
  }

  publish(id: number): Promise<{
    published: boolean;
    artifact_type: string;
    logical_id: string;
    version: number;
    checksum: string;
  }> {
    return request(this.url(`/drafts/${id}/publish/`), { method: "POST", body: "{}" });
  }
}
