import { useRef, useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type { ArtifactDraft, ArtifactPublishResult, DiagnosticsResult } from "./types";

export function ArtifactDraftEditor({
  api,
  draft,
  onChange,
  onClose,
  onPublished,
}: {
  api: BuilderApi;
  draft: ArtifactDraft;
  onChange: (draft: ArtifactDraft | null) => void;
  onClose: () => void;
  onPublished?: (result: ArtifactPublishResult) => void;
}) {
  const [name, setName] = useState(draft.name);
  const [bodyText, setBodyText] = useState(() => JSON.stringify(draft.body, null, 2));
  const [promptText, setPromptText] = useState(() =>
    typeof draft.body.template === "string" ? draft.body.template : "",
  );
  const [versionDescription, setVersionDescription] = useState("");
  const [diagnostics, setDiagnostics] = useState<DiagnosticsResult | null>(null);
  const [status, setStatus] = useState("");
  const versionDescriptionRef = useRef<HTMLInputElement>(null);

  function parsedBody(): Record<string, unknown> | null {
    try {
      const value = JSON.parse(bodyText) as unknown;
      if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
      const body = value as Record<string, unknown>;
      if (draft.artifact_type === "prompt_template") body.template = promptText;
      return body;
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

  async function save(): Promise<ArtifactDraft | null> {
    const body = parsedBody();
    if (!body) return null;
    try {
      const updated = await api.updateArtifactDraft(
        draft.id, { revision: draft.revision, name, body },
      );
      onChange(updated);
      setBodyText(JSON.stringify(updated.body, null, 2));
      setStatus("Taslak kaydedildi.");
      return updated;
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
      return null;
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

  async function publish() {
    if (!versionDescription.trim()) {
      setStatus("Bu sürümde nelerin değiştiğini yazın.");
      versionDescriptionRef.current?.focus();
      return;
    }
    const body = parsedBody();
    if (!body) return;
    try {
      let current = draft;
      if (JSON.stringify(body) !== JSON.stringify(draft.body) || name !== draft.name) {
        const saved = await save();
        if (!saved) return;
        current = saved;
      }
      const result = await api.publishArtifactDraft(
        current.id, current.revision, versionDescription,
      );
      const refreshed = await api.getArtifactDraft(current.id);
      onChange(refreshed);
      onPublished?.(result);
      setVersionDescription("");
      setStatus(`v${result.version} immutable olarak yayımlandı.`);
    } catch (error) {
      setStatus(error instanceof ApiError ? error.code : String(error));
    }
  }

  const title = draft.artifact_type === "input_contract"
    ? "Girdi sözleşmesi"
    : draft.artifact_type === "output_contract"
      ? "Çıktı sözleşmesi"
      : "Prompt şablonu";

  return <section>
    <button type="button" onClick={onClose}>← Taslaklar</button>
    <h2>{title}</h2>
    <label>Taslak adı<input aria-label="sözleşme taslak adı" value={name}
      disabled={!draft.can_write} onChange={(event) => setName(event.target.value)} /></label>
    <div><code>{draft.logical_id}</code></div>
    <p>{draft.logical_description}</p>
    {draft.last_published_version > 0 && <p>
      Son yayın: v{draft.last_published_version}
    </p>}
    {draft.artifact_type === "prompt_template" && <label>Prompt metni
      <textarea aria-label="prompt metni" rows={14} value={promptText}
        disabled={!draft.can_write} onChange={(event) => setPromptText(event.target.value)} />
    </label>}
    <details open={draft.artifact_type !== "prompt_template"}>
      <summary>Gelişmiş JSON</summary>
      <textarea aria-label="sözleşme JSON içeriği" rows={18} value={bodyText}
        disabled={!draft.can_write} onChange={(event) => setBodyText(event.target.value)} />
    </details>
    <div>
      <button type="button" onClick={() => void validate()}>Doğrula</button>
      {draft.can_write && <button type="button" disabled={!name.trim()}
        onClick={() => void save()}>Kaydet</button>}
      {draft.can_write && <button type="button" onClick={() => void remove()}>Sil</button>}
    </div>
    {draft.can_write && <div>
      <label>Exact version açıklaması<input ref={versionDescriptionRef}
        aria-label="artifact exact version açıklaması" maxLength={1000}
        value={versionDescription}
        placeholder="Bu sürümde ne değişti?"
        onChange={(event) => setVersionDescription(event.target.value)} /></label>
      <button type="button" onClick={() => void publish()}>Yayımla</button>
    </div>}
    {diagnostics && <div role="status">
      {diagnostics.ok ? "Taslak doğrulandı." : "Taslak geçersiz."}
      {diagnostics.errors.map((item) => <div key={item.code}>{item.code}: {item.message}</div>)}
    </div>}
    {status && <div role="alert">{status}</div>}
  </section>;
}
