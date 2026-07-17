import { useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type { AiCandidateResult } from "./types";

export function AiAuthoringPanel({ api, organization, projects, lockedProjectId, scenarioId, onGenerated }: {
  api: BuilderApi; organization: string; projects: { id: number; name: string }[];
  lockedProjectId?: number; scenarioId?: number;
  onGenerated: (result: AiCandidateResult, projectId: number) => void;
}) {
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState("");
  const [projectId, setProjectId] = useState(lockedProjectId ?? projects[0]?.id ?? 0);

  async function generate() {
    try {
      const generated = await api.generateCandidate({
        organization, project_id: projectId, scenario_id: scenarioId,
        description, artifact_type: "workflow_definition",
      });
      if (generated.status === "capability_missing") {
        setStatus(`Eksik yetenek: ${generated.required_capability}. Custom node taslağı önerisi hazır; henüz kaydedilmedi.`);
        return;
      }
      setStatus("");
      onGenerated(generated, projectId);
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  return <section style={{ marginTop: 20, borderTop: "1px solid #262b36", paddingTop: 16 }}>
    <label>Proje<select aria-label="AI projesi" value={projectId} disabled={!!lockedProjectId}
      onChange={(event) => setProjectId(Number(event.target.value))}>
      {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select></label>
    <h2>Scenario Studio AI planner</h2>
    <textarea aria-label="taslak açıklaması" rows={4} value={description}
      onChange={(event) => setDescription(event.target.value)} />
    <button type="button" disabled={!description.trim() || !scenarioId}
      onClick={() => void generate()}>Geçici aday üret</button>
    {status && <div role="alert">{status}</div>}
  </section>;
}
