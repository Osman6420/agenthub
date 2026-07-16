import { useCallback, useEffect, useState } from "react";

import { ApiError, BuilderApi } from "./api";
import { AiAuthoringPanel } from "./AiAuthoringPanel";
import { ArtifactDraftEditor } from "./ArtifactDraftEditor";
import { Editor } from "./Editor";
import type { ArtifactDraft, BuilderInitial, Draft, NodeSchema, OrgOption } from "./types";

// Top-level bootstrap: pick an organization (from the server-rendered scope), load its
// node-schema and drafts, then open or create a draft and hand off to the Editor. All
// data comes from the governed backend; the org list is the operator's server-side scope.
export function App({
  apiBase,
  orgs,
  initial,
}: {
  apiBase: string;
  orgs: OrgOption[];
  initial?: BuilderInitial;
}) {
  const [api] = useState(() => new BuilderApi(apiBase));
  const [orgSlug, setOrgSlug] = useState<string>(() =>
    initial?.organization && orgs.some((org) => org.slug === initial.organization)
      ? initial.organization
      : (orgs[0]?.slug ?? ""),
  );
  const [schema, setSchema] = useState<NodeSchema | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [artifactDrafts, setArtifactDrafts] = useState<ArtifactDraft[]>([]);
  const [active, setActive] = useState<Draft | null>(null);
  const [activeArtifact, setActiveArtifact] = useState<ArtifactDraft | null>(null);
  const [error, setError] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [newId, setNewId] = useState("");
  const [newJson, setNewJson] = useState("");
  const [deepLinkHandled, setDeepLinkHandled] = useState(false);
  const [scenarioAutoHandled, setScenarioAutoHandled] = useState(false);

  const org = orgs.find((o) => o.slug === orgSlug);
  const canWrite = !!org?.can_write;

  const reload = useCallback(async () => {
    if (!orgSlug) return;
    setError("");
    try {
      const [s, list, artifactList] = await Promise.all([
        api.nodeSchema(orgSlug), api.listDrafts(), api.listArtifactDrafts(),
      ]);
      setSchema(s);
      setDrafts(list.drafts.filter((d) => d.organization === orgSlug &&
        (!initial?.scenario_id || d.scenario_id === initial.scenario_id)));
      setArtifactDrafts(artifactList.drafts.filter((d) => d.organization === orgSlug));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    }
  }, [api, initial?.scenario_id, orgSlug]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const open = useCallback(
    async (id: number) => {
      try {
        setActive(await api.getDraft(id));
      } catch (err) {
        setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
      }
    },
    [api],
  );

  const openArtifact = useCallback(async (id: number) => {
    try {
      setActiveArtifact(await api.getArtifactDraft(id));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    }
  }, [api]);

  useEffect(() => {
    if (deepLinkHandled || !schema || !initial?.draft_id) return;
    setDeepLinkHandled(true);
    if (drafts.some((draft) => draft.id === initial.draft_id)) {
      void open(initial.draft_id);
    } else {
      setError("not_found: draft seçilen organizasyonun dışında");
    }
  }, [deepLinkHandled, drafts, initial?.draft_id, open, schema]);

  useEffect(() => {
    if (scenarioAutoHandled || !schema || !initial?.scenario_id || initial.draft_id) return;
    setScenarioAutoHandled(true);
    if (drafts.length > 0) void open(drafts[0].id);
  }, [drafts, initial?.draft_id, initial?.scenario_id, open, scenarioAutoHandled, schema]);

  const create = useCallback(async (bodyOverride?: Record<string, unknown>) => {
    try {
      let body = bodyOverride ?? {};
      if (!bodyOverride && newJson.trim()) {
        const parsed = JSON.parse(newJson) as unknown;
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          throw new Error("Geçerli bir JSON nesnesi girin");
        }
        body = parsed as Record<string, unknown>;
      }
      const draft = await api.createDraft({
        organization: orgSlug,
        ...(initial?.project_id ? { project_id: initial.project_id } : {}),
        ...(initial?.scenario_id ? { scenario_id: initial.scenario_id } : {}),
        name: newName,
        logical_id: newId,
        body,
      });
      setNewName("");
      setNewId("");
      setNewJson("");
      await reload();
      setActive(draft);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    }
  }, [api, initial?.project_id, initial?.scenario_id, newJson, newName, newId, orgSlug, reload]);

  const createFromActive = useCallback(async () => {
    if (!initial?.active_workflow || !initial.project_id || !initial.scenario_id) return;
    try {
      const draft = await api.createDraft({
        organization: orgSlug,
        project_id: initial.project_id,
        scenario_id: initial.scenario_id,
        name: initial.active_workflow.name,
        logical_id: `${initial.active_workflow.logical_id}_${initial.scenario_id}`.slice(0, 128),
        body: initial.active_workflow.body,
      });
      await reload();
      setActive(draft);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    }
  }, [api, initial?.active_workflow, initial?.project_id, initial?.scenario_id, orgSlug, reload]);

  const previewActive = useCallback(() => {
    if (!initial?.active_workflow || !initial.project_id || !initial.scenario_id) return;
    setActive({
      id: 0,
      organization: orgSlug,
      organization_id: 0,
      project_id: initial.project_id,
      scenario_id: initial.scenario_id,
      name: initial.active_workflow.name,
      logical_id: initial.active_workflow.logical_id,
      body: initial.active_workflow.body,
      last_published_version: initial.active_workflow.version,
      last_published_at: null,
      revision: 1,
      can_write: false,
    });
  }, [initial?.active_workflow, initial?.project_id, initial?.scenario_id, orgSlug]);

  if (active && schema) {
    return (
      <div>
        {initial?.scenario_id && <div style={{ padding: "8px 0 12px" }}>
          <strong>Scenario Studio · {initial.scenario_name}</strong>
          <span style={{ color: "#8b95a7", marginLeft: 8 }}>Proje: {initial.project_name}</span>
        </div>}
        <button type="button" onClick={() => setActive(null)} style={backBtn}>
          ← Draft'lar
        </button>
        <Editor api={api} schema={schema} draft={active} />
      </div>
    );
  }

  if (activeArtifact) {
    return <ArtifactDraftEditor api={api} draft={activeArtifact}
      onChange={(draft) => { setActiveArtifact(draft); void reload(); }}
      onClose={() => setActiveArtifact(null)} />;
  }

  return (
    <div style={{ maxWidth: 820 }}>
      {error && (
        <div role="alert" style={errorBox}>
          {error}
        </div>
      )}
      {initial?.scenario_id && <section style={{ padding: 12, marginBottom: 16, border: "1px solid #334155", borderRadius: 8 }}>
        <strong>Scenario Studio · {initial.scenario_name}</strong>
        <div style={{ color: "#8b95a7" }}>Proje: {initial.project_name} · Organizasyon: {org?.name}</div>
        <div style={{ fontSize: 13 }}>Bu sayfadaki workflow taslakları yalnız bu senaryoya aittir.</div>
      </section>}
      <div className="ah-builder-org-row">
        <label style={{ color: "#8b95a7", fontSize: 13 }}>
          Organizasyon
          <select
            aria-label="organizasyon"
            value={orgSlug}
            disabled={!!initial?.scenario_id}
            onChange={(e) => setOrgSlug(e.target.value)}
            style={{ marginLeft: 8, padding: "6px 8px" }}
          >
            {orgs.map((o) => (
              <option key={o.slug} value={o.slug}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        {!canWrite && <span style={{ color: "#fcd34d", fontSize: 12 }}>salt okunur</span>}
      </div>

      <h2 style={{ margin: "8px 0" }}>Draft'lar</h2>
      {drafts.length === 0 && <div style={{ color: "#8b95a7" }}>Henüz draft yok.</div>}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {drafts.map((d) => (
          <li key={d.id} className="ah-builder-draft-row" style={draftRow}>
            <span>
              <strong>{d.name}</strong>{" "}
              <span style={{ color: "#8b95a7" }}>({d.logical_id})</span>
              {d.last_published_version > 0 && (
                <span style={{ color: "#86efac", marginLeft: 8 }}>
                  v{d.last_published_version} yayımlandı
                </span>
              )}
            </span>
            <button type="button" onClick={() => void open(d.id)} style={openBtn}>
              Aç
            </button>
          </li>
        ))}
      </ul>

      {initial?.scenario_id && initial.active_workflow && drafts.length === 0 && <section
        style={{ padding: 12, margin: "16px 0", border: "1px solid #334155", borderRadius: 8 }}>
        <strong>Aktif workflow · v{initial.active_workflow.version}</strong>
        <div><code>{initial.active_workflow.logical_id}</code> · checksum {initial.active_workflow.checksum.slice(0, 12)}</div>
        <button type="button" onClick={previewActive} style={openBtn}>JSON/graph görüntüle</button>
        {canWrite && <button type="button" onClick={() => void createFromActive()}
          style={{ ...openBtn, marginLeft: 8 }}>Yeni taslak olarak düzenle</button>}
      </section>}

      <h2 style={{ margin: "20px 0 8px" }}>Sözleşme taslakları</h2>
      {artifactDrafts.length === 0 && <div style={{ color: "#8b95a7" }}>
        Henüz sözleşme taslağı yok.
      </div>}
      <ul style={{ listStyle: "none", padding: 0 }}>
        {artifactDrafts.map((draft) => <li key={draft.id} className="ah-builder-draft-row"
          style={draftRow}>
          <span><strong>{draft.name}</strong>{" "}<span style={{ color: "#8b95a7" }}>
            ({draft.artifact_type === "input_contract" ? "girdi" : "çıktı"}; {draft.logical_id})
          </span></span>
          <button type="button" onClick={() => void openArtifact(draft.id)} style={openBtn}>Aç</button>
        </li>)}
      </ul>

      {canWrite && schema && schema.projects.length > 0 && <AiAuthoringPanel api={api} organization={orgSlug} projects={schema.projects}
        lockedProjectId={initial?.project_id} scenarioId={initial?.scenario_id}
        onAccepted={(draft) => {
          void reload();
          if ("artifact_type" in draft) setActiveArtifact(draft);
          else setActive(draft);
        }} />}

      {canWrite && (
        <div className="ah-builder-create" style={{ marginTop: 20, borderTop: "1px solid #262b36", paddingTop: 16 }}>
          <h2 style={{ margin: "0 0 8px" }}>Yeni draft</h2>
          <input
            aria-label="draft adı"
            placeholder="Ad"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            style={createInput}
          />
          <input
            aria-label="logical id"
            placeholder="logical_id"
            value={newId}
            onChange={(e) => setNewId(e.target.value)}
            style={createInput}
          />
          {initial?.scenario_id && <textarea aria-label="yeni workflow JSON" rows={12}
            placeholder="İsteğe bağlı: agenthub/v1 Workflow JSON'unun tamamını buraya yapıştırın. Boş bırakırsanız graph ile başlayın."
            value={newJson} onChange={(event) => setNewJson(event.target.value)}
            style={{ display: "block", width: "100%", margin: "10px 0", fontFamily: "monospace" }} />}
          <button type="button" disabled={!newName || !newId} onClick={() => void create()} style={openBtn}>
            Oluştur
          </button>
        </div>
      )}
    </div>
  );
}

const backBtn: React.CSSProperties = {
  margin: "0 0 10px",
  padding: "6px 12px",
  borderRadius: 7,
  border: "1px solid #333a49",
  background: "#222835",
  color: "#e6e6e6",
  cursor: "pointer",
};
const openBtn: React.CSSProperties = {
  padding: "6px 12px",
  borderRadius: 7,
  border: 0,
  background: "#3b82f6",
  color: "#fff",
  cursor: "pointer",
};
const draftRow: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "10px 0",
  borderBottom: "1px solid #1f2530",
};
const createInput: React.CSSProperties = {
  padding: "6px 8px",
  marginRight: 8,
  borderRadius: 6,
  border: "1px solid #333a49",
  background: "#0f1115",
  color: "#e6e6e6",
};
const errorBox: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 7,
  background: "#3a2226",
  color: "#fca5a5",
  marginBottom: 12,
};
