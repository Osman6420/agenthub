import { useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type { AiCandidateResult, Draft } from "./types";

export function AiAuthoringPanel({ api, organization, projects, onAccepted }: {
  api: BuilderApi; organization: string; projects: { id: number; name: string }[];
  onAccepted: (draft: Draft) => void;
}) {
  const [description, setDescription] = useState("");
  const [name, setName] = useState("");
  const [logicalId, setLogicalId] = useState("");
  const [result, setResult] = useState<AiCandidateResult | null>(null);
  const [status, setStatus] = useState("");
  const [projectId, setProjectId] = useState(projects[0]?.id ?? 0);

  async function generate() {
    try {
      setResult(await api.generateCandidate({ organization, project_id: projectId, description }));
      setStatus("");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  async function accept() {
    if (!result) return;
    try {
      onAccepted(await api.acceptCandidate({
        organization, project_id: projectId, name, logical_id: logicalId,
        candidate: result.candidate,
      }));
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  return <section style={{ marginTop: 20, borderTop: "1px solid #262b36", paddingTop: 16 }}>
    <label>Proje<select aria-label="AI projesi" value={projectId}
      onChange={(event) => setProjectId(Number(event.target.value))}>
      {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select></label>
    <h2>AI ile workflow taslağı</h2>
    <textarea aria-label="senaryo açıklaması" rows={4} value={description}
      onChange={(event) => setDescription(event.target.value)} />
    <button type="button" disabled={!description.trim()} onClick={() => void generate()}>Aday üret</button>
    {result && <div role="status">
      {result.diagnostics.ok ? "Aday doğrulandı." : "Aday geçersiz."}
      {result.diagnostics.errors.map((item) => <div key={item.code}>{item.code}: {item.message}</div>)}
      <input aria-label="AI draft adı" value={name} onChange={(event) => setName(event.target.value)} />
      <input aria-label="AI logical id" value={logicalId}
        onChange={(event) => setLogicalId(event.target.value)} />
      <button type="button" disabled={!result.diagnostics.ok || !name || !logicalId}
        onClick={() => void accept()}>Adayı draft'a aktar ve aç</button>
    </div>}
    {status && <div role="alert">{status}</div>}
  </section>;
}
