import { useCallback, useEffect, useState } from "react";

import { ApiError, BuilderApi } from "./api";
import { AiAuthoringPanel } from "./AiAuthoringPanel";
import { ArtifactDraftEditor } from "./ArtifactDraftEditor";
import { Editor } from "./Editor";
import { ScenarioManifestPanel } from "./ScenarioManifestPanel";
import type { AiCandidateResult, ArtifactDraft, BuilderInitial, CapabilityMissingResult, Draft, NodeSchema, OrgOption } from "./types";

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
  const [newLogicalDescription, setNewLogicalDescription] = useState("");
  const [newJson, setNewJson] = useState("");
  const [deepLinkHandled, setDeepLinkHandled] = useState(false);
  const [scenarioAutoHandled, setScenarioAutoHandled] = useState(false);
  const [transient, setTransient] = useState<{ result: AiCandidateResult; projectId: number } | null>(null);
  const [capabilityScaffold, setCapabilityScaffold] = useState<{
    requiredCapability: string; displayName: string; purpose: string;
    inputSummary: string; configSummary: string; outputSummary: string;
  } | null>(null);

  const openCapabilityScaffold = useCallback((result: CapabilityMissingResult) => {
    const suggestion = result.suggestion;
    const text = (key: string) => typeof suggestion[key] === "string" ? suggestion[key] as string : "";
    setCapabilityScaffold({
      requiredCapability: result.required_capability,
      displayName: text("display_name"), purpose: text("purpose"),
      inputSummary: text("input_summary"), configSummary: text("config_summary"),
      outputSummary: text("output_summary"),
    });
  }, []);

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
        logical_description: newLogicalDescription,
        body,
      });
      setNewName("");
      setNewId("");
      setNewLogicalDescription("");
      setNewJson("");
      await reload();
      setActive(draft);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    }
  }, [api, initial?.project_id, initial?.scenario_id, newJson, newLogicalDescription, newName, newId, orgSlug, reload]);

  const createFromActive = useCallback(async () => {
    if (!initial?.active_workflow || !initial.project_id || !initial.scenario_id) return;
    try {
      const draft = await api.createDraft({
        organization: orgSlug,
        project_id: initial.project_id,
        scenario_id: initial.scenario_id,
        name: initial.active_workflow.name,
        logical_id: `${initial.active_workflow.logical_id}_${initial.scenario_id}`.slice(0, 128),
        logical_description: `${initial.scenario_name ?? "Senaryo"} aktif workflow kopyası`,
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
        <Editor api={api} schema={schema} draft={active}
          initialDiagnostics={active.id === 0 && transient ? transient.result.diagnostics : undefined}
          onRepairTransient={active.id === 0 && transient && initial?.scenario_id
            ? async (body, instruction) => {
              const result = await api.repairCandidate({
                organization: orgSlug,
                project_id: transient.projectId,
                scenario_id: initial.scenario_id as number,
                candidate: body,
                instruction,
                prompt_contract: transient.result.prompt_contract,
                authoring_context: transient.result.authoring_context,
              });
              if (result.status === "capability_missing") {
                openCapabilityScaffold(result);
                return null;
              }
              setTransient({ result, projectId: transient.projectId });
              return result;
            }
            : undefined}
          onSaveTransient={active.id === 0 && transient ? async (body, name) => {
            const existing = drafts[0];
            const updateExisting = existing ? window.confirm(
              `Bu scenario için “${existing.name}” taslağı var. Tamam: mevcut taslağı güncelle; İptal: yeni kopya oluştur.`,
            ) : false;
            const saved = await api.acceptCandidate({
              organization: orgSlug, project_id: transient.projectId,
              scenario_id: initial?.scenario_id, name,
              artifact_type: "workflow_definition", candidate: body,
              prompt_contract: transient.result.prompt_contract,
              authoring_context: transient.result.authoring_context,
              ...(updateExisting ? { draft_id: existing.id, revision: existing.revision } : {}),
            });
            if ("artifact_type" in saved) return;
            setTransient(null);
            await reload();
            setActive(saved);
          } : undefined} />
        {initial?.can_compile_release && initial.scenario_public_id &&
          initial.artifact_options_url && <ScenarioManifestPanel
            api={api}
            scenarioPublicId={initial.scenario_public_id}
            optionsUrl={initial.artifact_options_url}
          />}
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
              {d.logical_description && <div style={{ color: "#8b95a7", fontSize: 13 }}>
                {d.logical_description}
              </div>}
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

      {initial?.can_compile_release && initial.scenario_public_id &&
        initial.artifact_options_url && <ScenarioManifestPanel
          api={api}
          scenarioPublicId={initial.scenario_public_id}
          optionsUrl={initial.artifact_options_url}
        />}

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
        availability={initial?.ai_authoring}
        onCapabilityMissing={openCapabilityScaffold}
        onGenerated={(result, projectId) => {
          setCapabilityScaffold(null);
          setTransient({ result, projectId });
          setActive({
            id: 0, organization: orgSlug, organization_id: 0,
            project_id: projectId, scenario_id: initial?.scenario_id ?? null,
            name: initial?.scenario_name ? `${initial.scenario_name} workflow` : "AI workflow adayı",
            logical_id: "transient-ai-candidate", body: result.candidate,
            last_published_version: 0, last_published_at: null, revision: 1, can_write: true,
          });
        }} />}

      {capabilityScaffold && <section aria-label="Python node geçici taslağı"
        style={{ marginTop: 16, padding: 12, border: "1px solid #a16207", borderRadius: 8 }}>
        <strong>Review bekleyecek Python node önerisi</strong>
        <div>Eksik yetenek: <code>{capabilityScaffold.requiredCapability}</code></div>
        <label>Görünen ad<input aria-label="Python node görünen adı"
          value={capabilityScaffold.displayName}
          onChange={(event) => setCapabilityScaffold({ ...capabilityScaffold, displayName: event.target.value })} /></label>
        <label>Amaç<textarea aria-label="Python node amacı" value={capabilityScaffold.purpose}
          onChange={(event) => setCapabilityScaffold({ ...capabilityScaffold, purpose: event.target.value })} /></label>
        <label>Input özeti<textarea aria-label="Python node input özeti" value={capabilityScaffold.inputSummary}
          onChange={(event) => setCapabilityScaffold({ ...capabilityScaffold, inputSummary: event.target.value })} /></label>
        <label>Config özeti<textarea aria-label="Python node config özeti" value={capabilityScaffold.configSummary}
          onChange={(event) => setCapabilityScaffold({ ...capabilityScaffold, configSummary: event.target.value })} /></label>
        <label>Output özeti<textarea aria-label="Python node output özeti" value={capabilityScaffold.outputSummary}
          onChange={(event) => setCapabilityScaffold({ ...capabilityScaffold, outputSummary: event.target.value })} /></label>
        <p>Bu yalnız tarayıcı belleğindeki geçici scaffold’dur. Kod üretmez, DB kaydı oluşturmaz,
          review istemez ve node’u aktive etmez. P2.6.8 author draft API açıldığında normal
          draft → test → admin review yaşam döngüsüne aktarılacaktır.</p>
        <button type="button" onClick={() => setCapabilityScaffold(null)}>Öneriyi kapat</button>
      </section>}

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
          <textarea
            aria-label="logical artifact açıklaması"
            placeholder="Bu logical artifact hangi kalıcı amacı karşılıyor?"
            maxLength={1000}
            value={newLogicalDescription}
            onChange={(e) => setNewLogicalDescription(e.target.value)}
            style={{ display: "block", width: "100%", margin: "10px 0" }}
          />
          {initial?.scenario_id && <textarea aria-label="yeni workflow JSON" rows={12}
            placeholder="İsteğe bağlı: agenthub/v1 Workflow JSON'unun tamamını buraya yapıştırın. Boş bırakırsanız graph ile başlayın."
            value={newJson} onChange={(event) => setNewJson(event.target.value)}
            style={{ display: "block", width: "100%", margin: "10px 0", fontFamily: "monospace" }} />}
          <button type="button" disabled={!newName || !newId || !newLogicalDescription.trim()} onClick={() => void create()} style={openBtn}>
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
