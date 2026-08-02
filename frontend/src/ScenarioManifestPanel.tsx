import { useEffect, useMemo, useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type {
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
}: {
  api: BuilderApi;
  scenarioPublicId: string;
  optionsUrl: string;
}) {
  const [types, setTypes] = useState<ManifestTypeOption[]>([]);
  const [logicals, setLogicals] = useState<ManifestLogicalOption[]>([]);
  const [versions, setVersions] = useState<ManifestVersionOption[]>([]);
  const [roles, setRoles] = useState<string[]>([]);
  const [artifactType, setArtifactType] = useState("");
  const [logicalId, setLogicalId] = useState("");
  const [versionId, setVersionId] = useState("");
  const [role, setRole] = useState("");
  const [requiredRole, setRequiredRole] = useState("");
  const [selected, setSelected] = useState<SelectedManifestItem[]>([]);
  const [requirements, setRequirements] = useState<ManifestRequirement[]>([]);
  const [diagnostics, setDiagnostics] = useState<ReleaseDiagnostic[]>([]);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [releaseId, setReleaseId] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [dirtyNoticeVisible, setDirtyNoticeVisible] = useState(false);

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
  const duplicateVersion = selected.some((item) => item.artifact_version_id === selectedVersion?.id);
  const duplicateRole = selected.some((item) => item.role === role);
  const canAdd = Boolean(selectedVersion && role && !duplicateVersion && !duplicateRole);

  async function chooseType(value: string, requiredRole = "") {
    setArtifactType(value);
    setLogicalId("");
    setVersionId("");
    setRole(requiredRole);
    setRequiredRole(requiredRole);
    setLogicals([]);
    setVersions([]);
    setRoles([]);
    setDiagnostics([]);
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

  async function chooseLogical(value: string) {
    setLogicalId(value);
    setVersionId("");
    setRole(requiredRole);
    setVersions([]);
    setRoles([]);
    setDiagnostics([]);
    if (!value) return;
    try {
      const result = await api.manifestOptions(optionsUrl, {
        artifact_type: artifactType,
        logical_id: value,
      });
      if (result.level === "exact_version") {
        setVersions(result.options as ManifestVersionOption[]);
        setRoles(requiredRole
          ? [requiredRole, ...(result.roles ?? []).filter((item) => item !== requiredRole)]
          : (result.roles ?? []));
      }
    } catch (error) {
      setStatus(formatError(error));
    }
  }

  async function addSelection() {
    if (!selectedVersion || !canAdd) return;
    setSelected((current) => [
      ...current,
      {
        artifact_version_id: selectedVersion.id,
        role,
        artifactType,
        logicalId,
        version: selectedVersion.version,
        checksum: selectedVersion.checksum,
        description: selectedVersion.description,
      },
    ]);
    setDirty(true);
    setDirtyNoticeVisible(true);
    setDiagnostics([]);
    setStatus("Manifest değişti; kanonik ön kontrol yeniden çalıştırılmalıdır.");
    setReleaseId(null);
    setVersionId("");
    setRole("");
    setRequiredRole("");
    if (artifactType === "workflow_definition" && role === "workflow_definition") {
      try {
        const result = await api.manifestRequirements(
          scenarioPublicId,
          selectedVersion.id,
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
        Release adayı
      </div>
      <h2 id="manifest-heading">Kesin sürümlü candidate manifest</h2>
      <p style={{ color: "#8b95a7" }}>
        Yalnız immutable exact version pinlenir. Başarısız preflight veya compile seçimleri silmez;
        publish, evaluation ve promotion ayrı işlemlerdir.
      </p>
      <button type="button" disabled={busy} onClick={() => void loadMinimumPreset()}>
        Minimum release önerisini getir
      </button>
    </div>

    {dirty && dirtyNoticeVisible && <div role="alert" style={warningBox}>
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
          disabled={!logicalId} onChange={(event) => setVersionId(event.target.value)}>
          <option value="">Sürüm seçin</option>
          {versions.map((item) => <option key={item.id} value={item.id}>
            v{item.version} · {item.checksum.slice(0, 12)}
          </option>)}
        </select>
      </label>
      <label>Manifest rolü
        <select aria-label="Manifest rolü" value={role}
          disabled={!versionId || Boolean(requiredRole)}
          onChange={(event) => setRole(event.target.value)}>
          <option value="">Rol seçin</option>
          {roles.map((item) => <option key={item} value={item}>{item}</option>)}
        </select>
      </label>
      <button type="button" disabled={!canAdd}
        onClick={() => void addSelection()}>Manifest’e ekle</button>
    </div>

    {(duplicateVersion || duplicateRole) && <div role="alert" style={errorBox}>
      {duplicateVersion
        ? "Bu exact version zaten seçili."
        : "Bu manifest rolü zaten başka bir exact version tarafından kullanılıyor."}
    </div>}

    {selected.length === 0
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
      </ul>}

    {requirements.length > 0 && <div aria-label="Kanonik workflow gereksinimleri"
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

    {diagnostics.filter((entry) => !entry.role ||
      !selected.some((item) => item.role === entry.role)).map((entry) =>
      <div key={`${entry.code}-${entry.role ?? ""}`} role="alert" style={errorBox}>
        <code>{entry.code}</code>: {entry.message}
        {entry.role && <> · rol <code>{entry.role}</code></>}
        {entry.node_id && <> · node <code>{entry.node_id}</code></>}
      </div>)}

    <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
