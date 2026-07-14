import { useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type { AcceptedCandidateDraft, AiCandidateResult, AiCandidateType } from "./types";

export function AiAuthoringPanel({ api, organization, projects, onAccepted }: {
  api: BuilderApi; organization: string; projects: { id: number; name: string }[];
  onAccepted: (draft: AcceptedCandidateDraft) => void;
}) {
  const [description, setDescription] = useState("");
  const [name, setName] = useState("");
  const [logicalId, setLogicalId] = useState("");
  const [result, setResult] = useState<AiCandidateResult | null>(null);
  const [status, setStatus] = useState("");
  const [projectId, setProjectId] = useState(projects[0]?.id ?? 0);
  const [artifactType, setArtifactType] = useState<AiCandidateType>("workflow_definition");

  async function generate() {
    try {
      setResult(await api.generateCandidate({
        organization, project_id: projectId, description, artifact_type: artifactType,
      }));
      setStatus("");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  async function accept() {
    if (!result) return;
    try {
      const accepted = await api.acceptCandidate({
        organization, project_id: projectId, name, logical_id: logicalId,
        artifact_type: result.artifact_type, candidate: result.candidate,
        prompt_contract: result.prompt_contract,
      });
      setStatus("Aday taslağa aktarıldı.");
      onAccepted(accepted);
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  return <section style={{ marginTop: 20, borderTop: "1px solid #262b36", paddingTop: 16 }}>
    <label>Proje<select aria-label="AI projesi" value={projectId}
      onChange={(event) => setProjectId(Number(event.target.value))}>
      {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select></label>
    <label>Taslak türü<select aria-label="taslak türü" value={artifactType}
      onChange={(event) => { setArtifactType(event.target.value as AiCandidateType); setResult(null); }}>
      <option value="workflow_definition">Workflow</option>
      <option value="input_contract">Girdi sözleşmesi</option>
      <option value="output_contract">Çıktı sözleşmesi</option>
    </select></label>
    <h2>AI ile yönetilen taslak</h2>
    <textarea aria-label="taslak açıklaması" rows={4} value={description}
      onChange={(event) => setDescription(event.target.value)} />
    <button type="button" disabled={!description.trim()} onClick={() => void generate()}>Aday üret</button>
    {result && <div role="status">
      {result.diagnostics.ok ? "Aday doğrulandı." : "Aday geçersiz."}
      {result.diagnostics.errors.map((item) => <div key={item.code}>{item.code}: {item.message}</div>)}
      <input aria-label="AI taslak adı" value={name} onChange={(event) => setName(event.target.value)} />
      <input aria-label="AI logical id" value={logicalId}
        onChange={(event) => setLogicalId(event.target.value)} />
      <button type="button" disabled={!result.diagnostics.ok || !name || !logicalId}
        onClick={() => void accept()}>
        {result.artifact_type === "workflow_definition"
          ? "Adayı taslağa aktar ve aç"
          : "Adayı sözleşme taslağına aktar"}
      </button>
    </div>}
    {status && <div role="alert">{status}</div>}
  </section>;
}
