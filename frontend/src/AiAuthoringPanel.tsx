import { useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type { AiCandidateResult, CapabilityMissingResult } from "./types";

export function AiAuthoringPanel({ api, organization, projects, lockedProjectId, scenarioId, availability, onGenerated, onCapabilityMissing }: {
  api: BuilderApi; organization: string; projects: { id: number; name: string }[];
  lockedProjectId?: number; scenarioId?: number;
  availability?: { available: boolean; message: string };
  onGenerated: (result: AiCandidateResult, projectId: number) => void;
  onCapabilityMissing: (result: CapabilityMissingResult) => void;
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
        onCapabilityMissing(generated);
        return;
      }
      setStatus("");
      onGenerated(generated, projectId);
    } catch (error) {
      if (error instanceof ApiError && error.code === "ai_authoring_disabled") {
        setStatus("AI authoring kapalı: deployment yöneticisi onaylı immutable model profile ID ve provider yapılandırmalıdır.");
      } else if (error instanceof ApiError && error.code === "model_profile_unavailable") {
        setStatus("Yapılandırılan AI authoring model profili aktif veya erişilebilir değil; deployment ayarını doğrulayın.");
      } else {
        setStatus(error instanceof ApiError ? error.code : String(error));
      }
    }
  }

  return <section style={{ marginTop: 20, borderTop: "1px solid #262b36", paddingTop: 16 }}>
    <label>Proje<select aria-label="AI projesi" value={projectId} disabled={!!lockedProjectId}
      onChange={(event) => setProjectId(Number(event.target.value))}>
      {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
    </select></label>
    <h2>Scenario Studio AI planner</h2>
    {availability && <div role={availability.available ? "status" : "alert"}>
      {availability.message}
    </div>}
    <textarea aria-label="taslak açıklaması" rows={4} value={description}
      onChange={(event) => setDescription(event.target.value)} />
    <button type="button" disabled={!description.trim() || !scenarioId || availability?.available === false}
      onClick={() => void generate()}>Geçici aday üret</button>
    {status && <div role="alert">{status}</div>}
  </section>;
}
