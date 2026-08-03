import { useState } from "react";

import { ApiError, BuilderApi } from "./api";
import { defaultGovernedProfileBody, GovernedProfileEditor } from "./GovernedProfileEditor";
import type { ArtifactDraft } from "./types";

type ProfileType = "chunking_profile" | "retrieval_profile";

export function NewGovernedProfilePanel({ api, organization, projectId, scenarioId, onCreated }: {
  api: BuilderApi;
  organization: string;
  projectId: number;
  scenarioId: number;
  onCreated: (draft: ArtifactDraft) => void;
}) {
  const [type, setType] = useState<ProfileType>("chunking_profile");
  const [name, setName] = useState("");
  const [logicalId, setLogicalId] = useState("");
  const [description, setDescription] = useState("");
  const [body, setBody] = useState(() => defaultGovernedProfileBody("chunking_profile"));
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  async function create() {
    setBusy(true);
    setStatus("");
    try {
      const draft = await api.createArtifactDraft({
        organization,
        project_id: projectId,
        scenario_id: scenarioId,
        artifact_type: type,
        name,
        logical_id: logicalId,
        logical_description: description,
        body,
      });
      onCreated(draft);
    } catch (error) {
      setStatus(error instanceof ApiError ? `${error.code}: ${error.message}` : String(error));
    } finally {
      setBusy(false);
    }
  }

  return <section style={panelStyle}>
    <h3>Yeni parçalama / arama profili</h3>
    <label>Profil türü
      <select aria-label="yeni profil türü" value={type} onChange={(event) => {
        const nextType = event.target.value as ProfileType;
        setType(nextType);
        setBody(defaultGovernedProfileBody(nextType));
      }}>
        <option value="chunking_profile">Parçalama profili</option>
        <option value="retrieval_profile">Arama profili</option>
      </select>
    </label>
    <label>Ad<input aria-label="yeni profil adı" value={name}
      onChange={(event) => setName(event.target.value)} /></label>
    <label>Logical ID<input aria-label="yeni profil logical id" value={logicalId}
      onChange={(event) => setLogicalId(event.target.value)} /></label>
    <label>Kalıcı amaç<input aria-label="yeni profil açıklaması" value={description}
      maxLength={1000} onChange={(event) => setDescription(event.target.value)} /></label>
    <GovernedProfileEditor type={type} body={body} onChange={setBody} />
    <button type="button" disabled={busy || !name.trim() || !logicalId.trim() ||
      !description.trim()} onClick={() => void create()}>
      Profil taslağı oluştur
    </button>
    {status && <div role="alert">{status}</div>}
  </section>;
}

const panelStyle: React.CSSProperties = {
  marginTop: 16,
  padding: 12,
  border: "1px solid #334155",
  borderRadius: 8,
};
