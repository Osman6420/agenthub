import { useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type { ArtifactDraft, DiagnosticsResult } from "./types";

export function ArtifactDraftEditor({
  api,
  draft,
  onChange,
  onClose,
}: {
  api: BuilderApi;
  draft: ArtifactDraft;
  onChange: (draft: ArtifactDraft | null) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(draft.name);
  const [bodyText, setBodyText] = useState(() => JSON.stringify(draft.body, null, 2));
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResult | null>(null);
  const [status, setStatus] = useState("");

  function parsedBody(): Record<string, unknown> | null {
    try {
      const value = JSON.parse(bodyText) as unknown;
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
      return value as Record<string, unknown>;
    } catch {
      setStatus("Geçerli bir JSON nesnesi girin.");
      return null;
    }
  }

  async function validate() {
    const body = parsedBody();
    if (!body) return;
    try {
      setDiagnostics(await api.artifactDraftDiagnostics(draft.id, body));
      setStatus("");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  async function save() {
    const body = parsedBody();
    if (!body) return;
    try {
      const updated = await api.updateArtifactDraft(draft.id, { revision: draft.revision, name, body });
      onChange(updated);
      setStatus("Taslak kaydedildi.");
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  async function remove() {
    try {
      await api.deleteArtifactDraft(draft.id, draft.revision);
      onChange(null);
      onClose();
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  return <section>
    <button type="button" onClick={onClose}>← Taslaklar</button>
    <h2>{draft.artifact_type === "input_contract" ? "Girdi" : "Çıktı"} sözleşmesi</h2>
    <label>Taslak adı<input aria-label="sözleşme taslak adı" value={name}
      disabled={!draft.can_write} onChange={(event) => setName(event.target.value)} /></label>
    <div><code>{draft.logical_id}</code></div>
    <textarea aria-label="sözleşme JSON içeriği" rows={18} value={bodyText}
      disabled={!draft.can_write} onChange={(event) => setBodyText(event.target.value)} />
    <div>
      <button type="button" onClick={() => void validate()}>Doğrula</button>
      {draft.can_write && <button type="button" disabled={!name.trim()}
        onClick={() => void save()}>Kaydet</button>}
      {draft.can_write && <button type="button" onClick={() => void remove()}>Sil</button>}
    </div>
    {diagnostics && <div role="status">
      {diagnostics.ok ? "Taslak doğrulandı." : "Taslak geçersiz."}
      {diagnostics.errors.map((item) => <div key={item.code}>{item.code}: {item.message}</div>)}
    </div>}
    {status && <div role="alert">{status}</div>}
  </section>;
}
