import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, BuilderApi } from "./api";
import { announceArtifactPublished } from "./artifactPublication";
import { GovernedProfileEditor } from "./GovernedProfileEditor";
import { ModelProfileSelect } from "./ModelProfileSelect";
import type {
  ArtifactVersionPreview,
  ManifestLogicalOption,
  ManifestPresetOption,
  ManifestRequirement,
  ManifestSelectionPayload,
  ManifestTypeOption,
  ManifestVersionOption,
  ReleaseDiagnostic,
} from "./types";

type SelectedManifestItem = ManifestPresetOption;

export function ScenarioManifestPanel({
  api,
  scenarioPublicId,
  optionsUrl,
  organization,
  projectId,
  scenarioId,
  refreshArtifact,
  canCompileRelease = true,
}: {
  api: BuilderApi;
  scenarioPublicId: string;
  optionsUrl: string;
  organization?: string;
  projectId?: number;
  scenarioId?: number;
  refreshArtifact?: { id: number; artifactType: string; logicalId: string };
  canCompileRelease?: boolean;
}) {
  const [types, setTypes] = useState<ManifestTypeOption[]>([]);
  const [logicals, setLogicals] = useState<ManifestLogicalOption[]>([]);
  const [versions, setVersions] = useState<ManifestVersionOption[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [artifactType, setArtifactType] = useState("");
  const [logicalId, setLogicalId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [requiredRole, setRequiredRole] = useState("");
  const [selected, setSelected] = useState<SelectedManifestItem[]>([]);
  const [requirements, setRequirements] = useState<ManifestRequirement[]>([]);
  const [diagnostics, setDiagnostics] = useState<ReleaseDiagnostic[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [releaseId, setReleaseId] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [dirtyNoticeVisible, setDirtyNoticeVisible] = useState(false);
  const [preview, setPreview] = useState<ArtifactVersionPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [promptText, setPromptText] = useState("");
  const [artifactBody, setArtifactBody] = useState<Record<string, unknown>>({});
  const [versionDescription, setVersionDescription] = useState("");
  const versionDescriptionRef = useRef<HTMLInputElement>(null);
  const deepLinkAppliedRef = useRef(false);

  useEffect(() => {
    let active = true;
    void api.manifestOptions(optionsUrl).then((result) => {
      if (active && result.level === "artifact_type") {
        setTypes(result.options as ManifestTypeOption[]);
      }
    }).catch((error: unknown) => {
      if (active) setStatus(formatError(error));
    });
    return () => { active = false; };
  }, [api, optionsUrl]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function loadMinimumPreset() {
    setBusy(true);
    try {
      const result = await api.manifestOptions(optionsUrl, { preset: "minimum" });
      if (result.level !== "preset") return;
      setSelected(result.options as SelectedManifestItem[]);
      setDiagnostics([]);
      setRequirements([]);
      setReleaseId(null);
      setDirty(true);
      setDirtyNoticeVisible(true);
      const missing = result.missing_roles ?? [];
      setStatus(missing.length
        ? `Başlangıç önerisi yüklendi; eksik roller: ${missing.join(", ")}. Kanonik ön kontrol zorunludur.`
        : "Başlangıç önerisi yüklendi. Bu bir yetki veya yayın işlemi değildir; kanonik ön kontrol zorunludur.");
    } catch (error) {
      setStatus(formatError(error));
    } finally {
      setBusy(false);
    }
  }

  const selectedVersion = useMemo(
    () => versions.find((item) => String(item.id) === versionId),
    [versionId, versions],
  );
  const selectedType = useMemo(
    () => types.find((item) => item.value === artifactType),
    [artifactType, types],
  );
  const effectiveRole = requiredRole || roles[0] || artifactType;
  const originalPromptText = preview?.artifact_type === "prompt_template" &&
    typeof preview.body?.template === "string" ? preview.body.template : "";
  const promptChanged = preview?.artifact_type === "prompt_template" &&
    promptText !== originalPromptText;
  const profileChanged = (preview?.artifact_type === "chunking_profile" ||
    preview?.artifact_type === "retrieval_profile" ||
    preview?.artifact_type === "model_profile") &&
    JSON.stringify(artifactBody) !== JSON.stringify(preview.body ?? {});
  const artifactChanged = promptChanged || profileChanged;

  async function chooseType(value: string, requiredRole = "") {
    setArtifactType(value);
    setLogicalId("");
    setVersionId("");
    setRequiredRole(requiredRole);
    setLogicals([]);
    setVersions([]);
    setRoles([]);
    setDiagnostics([]);
    setPreview(null);
    setPromptText("");
    setArtifactBody({});
    setVersionDescription("");
    if (!value) return;
    try {
      const result = await api.manifestOptions(optionsUrl, { artifact_type: value });
      if (result.level === "logical_artifact") {
        setLogicals(result.options as ManifestLogicalOption[]);
      }
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  async function chooseLogical(value: string, selectVersionId = "") {
    setLogicalId(value);
    setVersionId("");
    setVersions([]);
    setRoles([]);
    setDiagnostics([]);
    setPreview(null);
    setPromptText("");
    setArtifactBody({});
    setVersionDescription("");
    if (!value) return;
    try {
      const result = await api.manifestOptions(optionsUrl, {
        artifact_type: artifactType,
        logical_id: value,
      });
      if (result.level === "exact_version") {
        setVersions(result.options as ManifestVersionOption[]);
        if (selectVersionId && (result.options as ManifestVersionOption[]).some(
          (item) => String(item.id) === selectVersionId,
        )) setVersionId(selectVersionId);
        setRoles(requiredRole
          ? [requiredRole, ...(result.roles ?? []).filter((item) => item !== requiredRole)]
          : (result.roles ?? []));
      }
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  useEffect(() => {
    if (!refreshArtifact) return;
    const target = refreshArtifact;
    let cancelled = false;
    async function selectPublishedArtifact() {
      setStatus("");
      setArtifactType(target.artifactType);
      setLogicalId(target.logicalId);
      try {
        const [logicalResult, versionResult] = await Promise.all([
          api.manifestOptions(optionsUrl, { artifact_type: target.artifactType }),
          api.manifestOptions(optionsUrl, {
            artifact_type: target.artifactType,
            logical_id: target.logicalId,
          }),
        ]);
        if (cancelled) return;
        if (logicalResult.level === "logical_artifact") {
          setLogicals(logicalResult.options as ManifestLogicalOption[]);
        }
        if (versionResult.level === "exact_version") {
          setVersions(versionResult.options as ManifestVersionOption[]);
          setVersionId(String(target.id));
          setRoles(versionResult.roles ?? []);
        }
      } catch (error) {
        if (!cancelled) setStatus(formatError(error));
      }
    }
    void selectPublishedArtifact();
    return () => { cancelled = true; };
  }, [api, optionsUrl, refreshArtifact]);

  useEffect(() => {
    if (deepLinkAppliedRef.current || refreshArtifact) return;
    deepLinkAppliedRef.current = true;
    const params = new URLSearchParams(window.location.search);
    const targetType = params.get("artifact_type") ?? "";
    const targetLogicalId = params.get("logical_id") ?? "";
    const targetVersionId = params.get("artifact_version_id") ?? "";
    if (!targetType || !targetLogicalId || !/^\d+$/.test(targetVersionId)) return;
    let cancelled = false;
    async function selectDeepLinkedArtifact() {
      try {
        const [logicalResult, versionResult] = await Promise.all([
          api.manifestOptions(optionsUrl, { artifact_type: targetType }),
          api.manifestOptions(optionsUrl, {
            artifact_type: targetType,
            logical_id: targetLogicalId,
          }),
        ]);
        if (cancelled) return;
        setArtifactType(targetType);
        setLogicalId(targetLogicalId);
        if (logicalResult.level === "logical_artifact") {
          setLogicals(logicalResult.options as ManifestLogicalOption[]);
        }
        if (versionResult.level === "exact_version") {
          const exactVersions = versionResult.options as ManifestVersionOption[];
          setVersions(exactVersions);
          setRoles(versionResult.roles ?? []);
          if (exactVersions.some((item) => String(item.id) === targetVersionId)) {
            setVersionId(targetVersionId);
          } else {
            setStatus("Deep link exact artifact bu senaryo için kullanılamıyor.");
          }
        }
      } catch (error) {
        if (!cancelled) setStatus(formatError(error));
      }
    }
    void selectDeepLinkedArtifact();
    return () => { cancelled = true; };
  }, [api, optionsUrl, refreshArtifact]);

  useEffect(() => {
    if (!selectedVersion) {
      setPreview(null);
      setPromptText("");
      setArtifactBody({});
      return;
    }
    let cancelled = false;
    setPreviewLoading(true);
    setPreview(null);
    setPromptText("");
    setArtifactBody({});
    setVersionDescription("");
    void api.artifactVersionPreview(scenarioPublicId, selectedVersion.id).then((result) => {
      if (cancelled) return;
      setPreview(result);
      setArtifactBody(result.body ?? {});
      setPromptText(result.artifact_type === "prompt_template" &&
        typeof result.body?.template === "string" ? result.body.template : "");
    }).catch((error: unknown) => {
      if (!cancelled) setStatus(formatError(error));
    }).finally(() => {
      if (!cancelled) setPreviewLoading(false);
    });
    return () => { cancelled = true; };
  }, [api, scenarioPublicId, selectedVersion]);

  async function applySelection(item: SelectedManifestItem) {
    setSelected((current) => [
      ...current.filter((candidate) => candidate.role !== item.role),
      item,
    ]);
    setDirty(true);
    setDirtyNoticeVisible(true);
    setDiagnostics([]);
    setStatus("Manifest değişti; kanonik ön kontrol yeniden çalıştırılmalıdır.");
    setReleaseId(null);
    if (item.artifactType === "workflow_definition" && item.role === "workflow_definition") {
      try {
        const result = await api.manifestRequirements(
          scenarioPublicId,
          item.artifact_version_id,
        );
        setDiagnostics(result.diagnostics);
        setRequirements(result.requirements ?? []);
        if (result.ok) {
          setStatus("Workflow bağımlılık rolleri kanonik grafikten çıkarıldı.");
        }
      } catch (error) {
        setStatus(formatError(error));
      }
    }
  }

  async function useSelectedVersion() {
    if (!selectedVersion || !effectiveRole) return;
    await applySelection({
      artifact_version_id: selectedVersion.id,
      role: effectiveRole,
      artifactType,
      logicalId,
      version: selectedVersion.version,
      checksum: selectedVersion.checksum,
      description: selectedVersion.description,
    });
  }

  async function publishChangedArtifact() {
    if (!preview || !artifactChanged || !effectiveRole) return;
    if (!versionDescription.trim()) {
      setStatus("Bu sürümde nelerin değiştiğini yazın.");
      versionDescriptionRef.current?.focus();
      return;
    }
    if (!organization || projectId === undefined || scenarioId === undefined) {
      setStatus("Yeni artifact sürümü için proje ve senaryo bağlamı bulunamadı.");
      return;
    }
    setBusy(true);
    setStatus("");
    try {
      let draft = await api.createArtifactDraft({
        organization,
        project_id: projectId,
        scenario_id: scenarioId,
        source_artifact_version_id: preview.id,
      });
      draft = await api.updateArtifactDraft(draft.id, {
        revision: draft.revision,
        body: preview.artifact_type === "prompt_template"
          ? { ...draft.body, template: promptText }
          : artifactBody,
      });
      const published = await api.publishArtifactDraft(
        draft.id, draft.revision, versionDescription.trim(),
      );
      announceArtifactPublished(
        published,
        preview.artifact_type === "prompt_template"
          ? { ...draft.body, template: promptText }
          : artifactBody,
      );
      if (canCompileRelease) {
        await applySelection({
          artifact_version_id: published.artifact_version_id,
          role: effectiveRole,
          artifactType: published.artifact_type,
          logicalId: published.logical_id,
          version: published.version,
          checksum: published.checksum,
          description: published.version_description,
        });
      }
      await chooseLogical(published.logical_id, String(published.artifact_version_id));
      setStatus(canCompileRelease
        ? `Yeni immutable ${published.artifact_type} v${published.version} yayımlandı ve manifest’e eklendi.`
        : `Yeni immutable ${published.artifact_type} v${published.version} yayımlandı.`);
    } catch (error) {
      setStatus(formatError(error));
    } finally {
      setBusy(false);
    }
  }

  function payload(): ManifestSelectionPayload[] {
    return selected.map(({ artifact_version_id, role: selectedRole }) => ({
      artifact_version_id,
      role: selectedRole,
    }));
  }

  async function preflight() {
    setBusy(true);
    setReleaseId(null);
    try {
      const result = await api.preflightManifest(scenarioPublicId, payload());
      setDiagnostics(result.diagnostics);
      setStatus(result.ok
        ? `Kanonik ön kontrol başarılı · sağlama ${result.artifact_manifest_sha256?.slice(0, 12)}`
        : "Kanonik ön kontrol düzeltme gerektiriyor; seçimler korundu.");
    } catch (error) {
      setStatus(formatError(error));
    } finally {
      setBusy(false);
    }
  }

  async function compile() {
    setBusy(true);
    setReleaseId(null);
    try {
      const result = await api.compileManifest(scenarioPublicId, payload());
      setDiagnostics(result.diagnostics);
      if (result.ok && result.release) {
        setReleaseId(result.release.id);
        setStatus(`Candidate release #${result.release.id} oluşturuldu; runtime değişmedi.`);
        setDirty(false);
        setDirtyNoticeVisible(false);
      } else {
        setStatus("Candidate oluşturulmadı; seçimler korundu ve hata aşağıda gösteriliyor.");
      }
    } catch (error) {
      setStatus(formatError(error));
    } finally {
      setBusy(false);
    }
  }

  return <section aria-labelledby="manifest-heading" style={panel}>
    <div>
      <div style={{ color: "#8b95a7", fontSize: 12, textTransform: "uppercase" }}>
        {canCompileRelease ? "Release adayı" : "Artifact workspace"}
      </div>
      <h2 id="manifest-heading">{canCompileRelease
        ? "Kesin sürümlü candidate manifest" : "Exact artifact içeriği ve sürümleme"}</h2>
      <p style={{ color: "#8b95a7" }}>
        {canCompileRelease
          ? "Yalnız immutable exact version pinlenir. Başarısız preflight veya compile seçimleri " +
            "silmez; publish, evaluation ve promotion ayrı işlemlerdir."
          : "Exact immutable içeriği inceleyebilir ve desteklenen türlerde yeni sürüm " +
            "yayımlayabilirsiniz. Bu alan candidate release oluşturmaz."}
      </p>
      {canCompileRelease && <button type="button" disabled={busy}
        onClick={() => void loadMinimumPreset()}>
        Minimum release önerisini getir
      </button>}
    </div>

    {canCompileRelease && dirty && dirtyNoticeVisible && <div role="alert" style={warningBox}>
      <strong>Kaydedilmemiş manifest seçimi var.</strong>
      <p>Seçim yalnızca bu tarayıcı belleğinde tutulur; henüz candidate release değildir.</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="button" disabled={busy || selected.length === 0}
          onClick={() => void compile()}>Candidate olarak kaydet</button>
        <button type="button" onClick={() => {
          setSelected([]);
          setDiagnostics([]);
          setReleaseId(null);
          setDirty(false);
          setDirtyNoticeVisible(false);
          setStatus("Manifest seçimi silindi.");
        }}>Seçimi sil</button>
        <button type="button" onClick={() => setDirtyNoticeVisible(false)}>
          Düzenlemeye devam et
        </button>
      </div>
    </div>}

    <div style={selectorGrid}>
      <label>Artifact türü
        <select aria-label="Manifest artifact türü" value={artifactType}
          onChange={(event) => void chooseType(event.target.value)}>
          <option value="">Tür seçin</option>
          {types.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </label>
      <label>Mantıksal artifact
        <select aria-label="Manifest mantıksal artifactı" value={logicalId}
          disabled={!artifactType} onChange={(event) => void chooseLogical(event.target.value)}>
          <option value="">Mantıksal artifact seçin</option>
          {logicals.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
        </select>
      </label>
      <label>Kesin sürüm
        <select aria-label="Manifest kesin sürümü" value={versionId}
          disabled={!logicalId} onChange={(event) => {
            setVersionId(event.target.value);
          }}>
          <option value="">Sürüm seçin</option>
          {versions.map((item) => <option key={item.id} value={item.id}>
            v{item.version} · {item.checksum.slice(0, 12)}
          </option>)}
        </select>
      </label>
    </div>

    {selectedType?.authoring_message && <p role="status">
      <strong>{selectedType.authoring_capability === "read_only"
        ? "Salt okunur" : selectedType.authoring_capability === "guided_elsewhere"
          ? "Ayrı authoring ekranı" : "Bu ekranda düzenlenebilir"}:</strong>{" "}
      {selectedType.authoring_message ?? selectedType.description}
    </p>}

    {previewLoading && <p role="status">Artifact içeriği yükleniyor…</p>}

    {preview && <section aria-label="Exact artifact önizleme" style={selectedRow}>
      <div style={{ minWidth: 0, width: "100%" }}>
        <strong>{preview.logical_id}:v{preview.version}</strong>
        <div>{preview.artifact_type} · sha256 {preview.checksum.slice(0, 12)}</div>
        <p>{preview.logical_description}</p>
        {preview.body_too_large
          ? <div role="alert">İçerik güvenli önizleme sınırını aşıyor.</div>
          : preview.artifact_type === "prompt_template"
            ? <label style={{ display: "block" }}>Prompt metni
                <textarea aria-label="Seçili prompt metni" rows={12} value={promptText}
                  readOnly={!preview.can_create_new_version}
                  onChange={(event) => setPromptText(event.target.value)}
                  style={{ width: "100%", marginTop: 6 }} />
              </label>
            : preview.artifact_type === "chunking_profile" ||
                preview.artifact_type === "retrieval_profile"
              ? null
              : preview.artifact_type === "model_profile" && organization &&
                  projectId !== undefined && scenarioId !== undefined
                ? <ModelProfileSelect api={api} organization={organization}
                    projectId={projectId} scenarioId={scenarioId}
                    value={typeof artifactBody.profile_id === "string"
                      ? artifactBody.profile_id : ""}
                    onChange={(profileId) => setArtifactBody({ profile_id: profileId })}
                    readOnly={!preview.can_create_new_version} />
              : <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                  {JSON.stringify(preview.body, null, 2)}
                </pre>}
        {(preview.artifact_type === "chunking_profile" ||
          preview.artifact_type === "retrieval_profile") && !preview.body_too_large &&
          <GovernedProfileEditor type={preview.artifact_type} body={artifactBody}
            onChange={setArtifactBody} readOnly={!preview.can_create_new_version} />}
        {artifactChanged && preview.can_create_new_version && <label style={{ display: "block" }}>
          Bu sürümde neler değişti?
          <input ref={versionDescriptionRef} aria-label="Prompt sürüm değişiklikleri"
            value={versionDescription}
            onChange={(event) => setVersionDescription(event.target.value)}
            style={{ width: "100%", marginTop: 6 }} />
        </label>}
        <div style={{ marginTop: 10 }}>
          {artifactChanged && preview.can_create_new_version
            ? <button type="button" disabled={busy} onClick={() => void publishChangedArtifact()}>
                Yeni sürümü yayımla ve ekle
              </button>
            : canCompileRelease && <button type="button" disabled={busy || !effectiveRole}
                onClick={() => void useSelectedVersion()}>
                Bu exact sürümü ekle
              </button>}
        </div>
      </div>
    </section>}

    {canCompileRelease && (selected.length === 0
      ? <p style={{ color: "#8b95a7" }}>Henüz exact artifact seçilmedi.</p>
      : <ul aria-label="Seçili manifest artifact’ları" style={{ listStyle: "none", padding: 0 }}>
        {selected.map((item) => {
          const itemDiagnostics = diagnostics.filter((entry) => entry.role === item.role);
          return <li key={item.artifact_version_id} style={{
            ...selectedRow,
            borderColor: itemDiagnostics.length ? "#ef4444" : "#334155",
          }}>
            <div>
              <strong>{item.role}</strong>
              <div>{item.artifactType} · {item.logicalId}:v{item.version}</div>
              <div style={{ color: "#8b95a7", fontSize: 12 }}>
                sağlama {item.checksum.slice(0, 12)} · {item.description}
              </div>
              {itemDiagnostics.map((entry) => <div key={entry.code} role="alert"
                style={{ color: "#fca5a5" }}>{entry.code}: {entry.message}</div>)}
            </div>
            <button type="button" onClick={() => {
              setSelected((current) => current.filter(
                (candidate) => candidate.artifact_version_id !== item.artifact_version_id,
              ));
              setDiagnostics([]);
              setReleaseId(null);
              setDirty(true);
              setDirtyNoticeVisible(true);
            }}>Kaldır</button>
          </li>;
        })}
      </ul>)}

    {canCompileRelease && requirements.length > 0 &&
      <div aria-label="Kanonik workflow gereksinimleri"
      style={{ margin: "12px 0" }}>
      <strong>Workflow dependency rolleri</strong>
      <p style={{ color: "#8b95a7", marginTop: 4 }}>
        Roller kesin workflow’un kanonik derlenmiş grafiğinden çıkarıldı. Eksik roller için
        immutable artifact/version seçimi sizde kalır.
      </p>
      {requirements.map((requirement) => {
        const satisfied = selected.some((item) =>
          item.role === requirement.role && item.artifactType === requirement.artifact_type);
        return <div key={requirement.role} style={{
          ...selectedRow,
          borderColor: satisfied ? "#166534" : "#a16207",
        }}>
          <div>
            <strong>{requirement.role}</strong> · {requirement.artifact_type}
            <div style={{ color: satisfied ? "#86efac" : "#fcd34d", fontSize: 12 }}>
              {satisfied ? "Exact pin seçildi" : "Exact pin eksik"}
              {requirement.node_ids.length > 0 &&
                ` · node ${requirement.node_ids.join(", ")}`}
            </div>
          </div>
          {!satisfied && <button type="button" onClick={() => {
            void chooseType(requirement.artifact_type, requirement.role);
          }}>Bu rol için artifact seç</button>}
        </div>;
      })}
    </div>}

    {canCompileRelease && diagnostics.filter((entry) => !entry.role ||
      !selected.some((item) => item.role === entry.role)).map((entry) =>
      <div key={`${entry.code}-${entry.role ?? ""}`} role="alert" style={errorBox}>
        <code>{entry.code}</code>: {entry.message}
        {entry.role && <> · rol <code>{entry.role}</code></>}
        {entry.node_id && <> · node <code>{entry.node_id}</code></>}
      </div>)}

    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
      {canCompileRelease && <>
      <button type="button" disabled={busy || selected.length === 0}
        onClick={() => void preflight()}>Kanonik ön kontrol</button>
      <button type="button" disabled={busy || selected.length === 0}
        onClick={() => void compile()}>Candidate release derle</button>
      <button type="button" disabled={busy || selected.length === 0} onClick={() => {
        setSelected([]);
        setDiagnostics([]);
        setStatus("Manifest seçimi temizlendi.");
        setReleaseId(null);
        setDirty(false);
        setDirtyNoticeVisible(false);
      }}>Seçimi temizle</button>
      </>}
      {status && <span role="status">{status}</span>}
      {releaseId && <a href={`/console/releases/${releaseId}/`}>Candidate #{releaseId} aç</a>}
    </div>
  </section>;
}

function formatError(error: unknown): string {
  return error instanceof ApiError ? `${error.code}: ${error.message}` : String(error);
}

const panel: React.CSSProperties = {
  marginTop: 20,
  padding: 16,
  border: "1px solid #334155",
  borderRadius: 8,
};

const selectorGrid: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 10,
  alignItems: "end",
};

const selectedRow: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  padding: 10,
  marginBottom: 8,
  border: "1px solid #334155",
  borderRadius: 7,
};

const errorBox: React.CSSProperties = {
  margin: "8px 0",
  padding: "8px 12px",
  borderRadius: 7,
  background: "#3a2226",
  color: "#fca5a5",
};

const warningBox: React.CSSProperties = {
  margin: "12px 0",
  padding: "12px",
  border: "1px solid #a16207",
  borderRadius: 7,
  background: "#33250f",
  color: "#fde68a",
};
