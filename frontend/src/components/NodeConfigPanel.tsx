import type { Node } from "@xyflow/react";
import { useEffect, useState } from "react";
import { ApiError, type BuilderApi } from "../api";
import { defaultGovernedProfileBody, GovernedProfileEditor } from "../GovernedProfileEditor";
import { ModelProfileSelect } from "../ModelProfileSelect";
import { fieldOptions, nodeTypeSchema } from "../schema";
import type {
  BuilderNodeData,
  Draft,
  GenerateNodeBinding,
  RetrieveNodeBinding,
  MappingEntry,
  NodeArtifactEntry,
  NodeConfig,
  NodeFieldSchema,
  NodeSchema,
  RetryPolicy,
} from "../types";

// Version history and "start from an existing one" for a node-owned artifact. Reverting
// republishes an old body *forward* (immutability is preserved), and copying takes a body
// from another logical artifact without pinning it — neither needs a raw logical id.
function ArtifactReuse({
  api,
  draftId,
  nodeId,
  kind,
  disabled,
  onUse,
}: {
  api: BuilderApi;
  draftId: number;
  nodeId: string;
  kind: "prompt" | "model" | "retrieval";
  disabled: boolean;
  onUse: (body: Record<string, unknown>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState<NodeArtifactEntry[]>([]);
  const [library, setLibrary] = useState<NodeArtifactEntry[]>([]);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (!open || draftId === 0) return;
    let active = true;
    void api.nodeArtifactLibrary(draftId, nodeId, kind).then((result) => {
      if (!active) return;
      setVersions(result.versions);
      setLibrary(result.library);
    }).catch((error: unknown) => {
      if (active) {
        setStatus(error instanceof ApiError ? `${error.code}: ${error.message}` : String(error));
      }
    });
    return () => { active = false; };
  }, [api, draftId, kind, nodeId, open]);

  function useEntry(entry: NodeArtifactEntry, label: string) {
    if (entry.body_too_large || entry.body === null) {
      setStatus("İçerik güvenli önizleme sınırını aşıyor.");
      return;
    }
    onUse(entry.body);
    setStatus(`${label} yüklendi. Kaydettiğinizde yeni bir sürüm olarak yayımlanır.`);
  }

  return <div style={{ marginTop: 8 }}>
    <button type="button" onClick={() => setOpen((value) => !value)}>
      {open ? "Geçmişi gizle" : "Geçmiş ve hazır profiller"}
    </button>
    {open && <div style={{ marginTop: 6 }}>
      <strong style={helpStyle}>Bu adımın sürümleri</strong>
      {versions.length === 0 && <div style={helpStyle}>Henüz yayımlanmış sürüm yok.</div>}
      <ul style={{ listStyle: "none", padding: 0, margin: "4px 0 0" }}>
        {versions.map((entry) => <li key={entry.artifact_version_id} style={{ marginTop: 4 }}>
          v{entry.version} · {entry.version_description || "açıklama yok"}
          {!disabled && <button type="button" style={{ marginLeft: 6 }}
            onClick={() => useEntry(entry, `v${entry.version}`)}>Bu sürüme dön</button>}
        </li>)}
      </ul>
      <strong style={helpStyle}>Mevcut bir profilden kopyala</strong>
      {library.length === 0 && <div style={helpStyle}>Kopyalanabilir başka profil yok.</div>}
      <ul style={{ listStyle: "none", padding: 0, margin: "4px 0 0" }}>
        {library.map((entry) => <li key={entry.artifact_version_id} style={{ marginTop: 4 }}>
          {entry.logical_description || entry.logical_id} · v{entry.version}
          {!disabled && <button type="button" style={{ marginLeft: 6 }}
            onClick={() => useEntry(entry, "Kopya")}>Kopyala</button>}
        </li>)}
      </ul>
      {status && <div role="status" style={helpStyle}>{status}</div>}
    </div>}
  </div>;
}

// Renders a config form for the selected node, generated entirely from the backend
// node-schema. Enum fields (tool binding_role, custom node_ref) are populated from the
// schema's role/ref lists — the UI never surfaces tool endpoints or secret values. Beyond
// ``config``, mapping-eligible nodes get input/output mapping editors, retry-eligible nodes
// a retry_policy editor, and tool nodes a compensation reference. None of this is
// authoritative: the backend compiler validates every field on diagnose/publish.
export function NodeConfigPanel({
  schema,
  node,
  disabled,
  onChange,
  onPatchData,
  onRemove,
  api,
  draft,
  onSaveGenerateBinding,
  onSaveRetrieveBinding,
}: {
  schema: NodeSchema;
  node: Node<BuilderNodeData> | null;
  disabled: boolean;
  onChange: (id: string, config: NodeConfig) => void;
  onPatchData: (id: string, patch: Partial<BuilderNodeData>) => void;
  onRemove: () => void;
  api: BuilderApi;
  draft: Draft;
  onSaveGenerateBinding: (
    nodeId: string, promptText: string, modelProfileId: string,
  ) => Promise<GenerateNodeBinding>;
  onSaveRetrieveBinding: (
    nodeId: string, profileBody: Record<string, unknown>,
  ) => Promise<RetrieveNodeBinding>;
}) {
  if (!node) {
    return (
      <aside className="ah-builder-config" style={panelStyle}>
        <div style={{ color: "#8b95a7" }}>Yapılandırmak için bir node seçin.</div>
      </aside>
    );
  }
  const typeSchema = nodeTypeSchema(schema, node.data.nodeType);
  const config = node.data.config ?? {};

  const setField = (name: string, value: unknown, required: boolean) => {
    const next = { ...config };
    if (!required && (value === "" || value === undefined)) delete next[name];
    else next[name] = value;
    onChange(node.id, next);
  };

  const composition = typeSchema?.composition === true;
  const agentLoop = typeSchema?.agent_loop === true;
  const gated =
    (composition && schema.gates?.composition_enabled === false) ||
    (agentLoop && schema.gates?.agent_loop_enabled === false);
  const gateLabel = agentLoop ? "agent_loop gate" : "composition gate";

  return (
    <aside className="ah-builder-config" style={panelStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{node.data.nodeType}</div>
      <div style={{ color: "#8b95a7", fontSize: 12, marginBottom: 12 }}>id: {node.id}</div>

      {gated && (
        <div role="note" style={gatedStyle}>
          Bu düğüm dağıtımda kapalı ({gateLabel}). Yayımlanabilir ancak sunucu
          etkinleştirilene kadar reddeder.
        </div>
      )}

      {typeSchema && typeSchema.fields.length === 0 &&
        !["generate", "retrieve"].includes(node.data.nodeType) && (
        <div style={{ color: "#8b95a7", fontSize: 13 }}>Bu node için yapılandırma yok.</div>
      )}

      {node.data.nodeType === "generate" && (
        <GenerateBindingEditor
          api={api}
          draft={draft}
          nodeId={node.id}
          disabled={disabled}
          onSave={onSaveGenerateBinding}
        />
      )}

      {node.data.nodeType === "retrieve" && (
        <RetrieveBindingEditor
          api={api}
          draft={draft}
          nodeId={node.id}
          disabled={disabled}
          onSave={onSaveRetrieveBinding}
        />
      )}

      {typeSchema?.fields.filter((field) =>
        node.data.nodeType !== "generate" ||
        (field.name !== "prompt_ref" && field.name !== "model_profile_ref")
      ).map((field) => (
        <FieldInput
          key={field.name}
          schema={schema}
          field={field}
          value={config[field.name]}
          disabled={disabled}
          onChange={(value) => setField(field.name, value, !!field.required)}
        />
      ))}

      {typeSchema?.supports_mapping && (
        <>
          <MappingSection
            title={`Girdi eşlemesi${typeSchema.mapping_required ? " *" : ""}`}
            ariaLabel="input_mapping"
            entries={node.data.input_mapping ?? []}
            disabled={disabled}
            onChange={(entries) => onPatchData(node.id, { input_mapping: entries })}
          />
          <MappingSection
            title={`Çıktı eşlemesi${typeSchema.mapping_required ? " *" : ""}`}
            ariaLabel="output_mapping"
            entries={node.data.output_mapping ?? []}
            disabled={disabled}
            onChange={(entries) => onPatchData(node.id, { output_mapping: entries })}
          />
        </>
      )}

      {typeSchema?.supports_retry && schema.retry_policy && (
        <RetrySection
          policy={node.data.retry_policy}
          limits={schema.retry_policy}
          disabled={disabled}
          onChange={(policy) => onPatchData(node.id, { retry_policy: policy })}
        />
      )}

      {typeSchema?.supports_compensation && (
        <label style={labelStyle}>
          Telafi (compensation) node
          <input
            aria-label="compensation"
            disabled={disabled}
            value={typeof node.data.compensation === "string" ? node.data.compensation : ""}
            onChange={(e) =>
              onPatchData(node.id, { compensation: e.target.value || undefined })
            }
            style={inputStyle}
          />
          <span style={helpStyle}>Hata durumunda çalıştırılacak tool node id'si.</span>
        </label>
      )}

      {!disabled && (
        <button type="button" onClick={onRemove} style={removeStyle}>
          Node'u kaldır
        </button>
      )}
    </aside>
  );
}

function RetrieveBindingEditor({
  api,
  draft,
  nodeId,
  disabled,
  onSave,
}: {
  api: BuilderApi;
  draft: Draft;
  nodeId: string;
  disabled: boolean;
  onSave: (
    nodeId: string, profileBody: Record<string, unknown>,
  ) => Promise<RetrieveNodeBinding>;
}) {
  const [profileBody, setProfileBody] = useState<Record<string, unknown>>(
    () => defaultGovernedProfileBody("retrieval_profile"),
  );
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(draft.id > 0);

  useEffect(() => {
    if (draft.id === 0) return;
    let active = true;
    setLoading(true);
    setStatus("");
    void api.retrieveNodeBinding(draft.id, nodeId).then((binding) => {
      if (!active) return;
      setProfileBody(binding.profile_body);
      setStatus(binding.configured
        ? "Node arama profili yüklendi."
        : "Mevcut release profili başlangıç değeri olarak yüklendi; kaydedince node'a özel olur.");
    }).catch((error: unknown) => {
      if (!active) return;
      setStatus(error instanceof ApiError && error.code === "retrieve_node_not_found"
        ? "Yeni node: arama ayarlarını girip kaydedebilirsiniz."
        : error instanceof ApiError ? `${error.code}: ${error.message}` : String(error));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, draft.id, nodeId]);

  if (draft.id === 0 || draft.project_id === null || draft.scenario_id === null) {
    return <div role="note" style={gatedStyle}>
      Arama profilini bağlamak için önce workflow adayını scenario taslağı olarak kaydedin.
    </div>;
  }

  return <fieldset style={{ ...labelStyle, border: "1px solid #334155", borderRadius: 6, padding: 10 }}>
    <legend>Retrieval ayarları</legend>
    <GovernedProfileEditor
      type="retrieval_profile"
      body={profileBody}
      onChange={setProfileBody}
      readOnly={disabled || loading}
    />
    {!disabled && <button type="button" disabled={loading} onClick={() => {
      setLoading(true);
      setStatus("");
      void onSave(nodeId, profileBody).then((binding) => {
        setProfileBody(binding.profile_body);
        setStatus("Arama profili bu Retrieve node'una kaydedildi.");
      }).catch((error: unknown) => {
        setStatus(error instanceof ApiError ? `${error.code}: ${error.message}` : String(error));
      }).finally(() => setLoading(false));
    }}>Arama profilini kaydet</button>}
    <ArtifactReuse api={api} draftId={draft.id} nodeId={nodeId} kind="retrieval"
      disabled={disabled || loading}
      onUse={(body) => setProfileBody(body)} />
    {status && <div role="status" style={helpStyle}>{status}</div>}
    <span style={helpStyle}>Artifact rolü sistem tarafından yönetilir; workflow JSON'unda gizli ref olarak tutulur.</span>
  </fieldset>;
}

function GenerateBindingEditor({
  api,
  draft,
  nodeId,
  disabled,
  onSave,
}: {
  api: BuilderApi;
  draft: Draft;
  nodeId: string;
  disabled: boolean;
  onSave: (
    nodeId: string, promptText: string, modelProfileId: string,
  ) => Promise<GenerateNodeBinding>;
}) {
  const [promptText, setPromptText] = useState("");
  const [modelProfileId, setModelProfileId] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(draft.id > 0);

  useEffect(() => {
    if (draft.id === 0) return;
    let active = true;
    setLoading(true);
    setStatus("");
    void api.generateNodeBinding(draft.id, nodeId).then((binding) => {
      if (!active) return;
      setPromptText(binding.prompt_text);
      setModelProfileId(binding.model_profile_id);
      setStatus(binding.configured ? "Node binding yüklendi." : "Bu node henüz kendi binding'ini kullanmıyor.");
    }).catch((error: unknown) => {
      if (!active) return;
      setStatus(error instanceof ApiError && error.code === "generate_node_not_found"
        ? "Yeni node: prompt ve modeli girip kaydedebilirsiniz."
        : error instanceof ApiError ? `${error.code}: ${error.message}` : String(error));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [api, draft.id, nodeId]);

  if (draft.id === 0 || draft.project_id === null || draft.scenario_id === null) {
    return <div role="note" style={gatedStyle}>
      Prompt ve model seçimini bağlamak için önce workflow adayını scenario taslağı olarak kaydedin.
    </div>;
  }

  const saveDisabled = disabled || loading || !promptText.trim() || !modelProfileId;
  return <fieldset style={{ ...labelStyle, border: "1px solid #334155", borderRadius: 6, padding: 10 }}>
    <legend>Üretim ayarları</legend>
    <label style={labelStyle}>Prompt metni
      <textarea
        aria-label="Generate prompt metni"
        disabled={disabled || loading}
        value={promptText}
        rows={8}
        onChange={(event) => setPromptText(event.target.value)}
        style={{ ...inputStyle, fontFamily: "monospace" }}
      />
    </label>
    <ModelProfileSelect
      api={api}
      organization={draft.organization}
      projectId={draft.project_id}
      scenarioId={draft.scenario_id}
      value={modelProfileId}
      onChange={setModelProfileId}
      readOnly={disabled}
    />
    {!disabled && <button type="button" disabled={saveDisabled} onClick={() => {
      setLoading(true);
      setStatus("");
      void onSave(nodeId, promptText, modelProfileId).then((binding) => {
        setPromptText(binding.prompt_text);
        setModelProfileId(binding.model_profile_id);
        setStatus("Prompt ve model bu Generate node'una kaydedildi.");
      }).catch((error: unknown) => {
        setStatus(error instanceof ApiError ? `${error.code}: ${error.message}` : String(error));
      }).finally(() => setLoading(false));
    }}>Prompt ve modeli kaydet</button>}
    <ArtifactReuse api={api} draftId={draft.id} nodeId={nodeId} kind="prompt"
      disabled={disabled || loading}
      onUse={(body) => setPromptText(typeof body.template === "string" ? body.template : "")} />
    {status && <div role="status" style={helpStyle}>{status}</div>}
    <span style={helpStyle}>Artifact rolleri sistem tarafından yönetilir; workflow JSON'unda gizli ref olarak tutulur.</span>
  </fieldset>;
}

function FieldInput({
  schema,
  field,
  value,
  disabled,
  onChange,
}: {
  schema: NodeSchema;
  field: NodeFieldSchema;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const label = `${field.name}${field.required ? " *" : ""}`;

  if (field.kind === "enum") {
    const options = fieldOptions(schema, field);
    return (
      <label style={labelStyle}>
        {label}
        <select
          aria-label={field.name}
          disabled={disabled}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          style={inputStyle}
        >
          <option value="">—</option>
          {options.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    );
  }

  if (field.kind === "boolean") {
    return (
      <label style={{ ...labelStyle, display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="checkbox"
          aria-label={field.name}
          disabled={disabled}
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    );
  }

  if (field.kind === "integer") {
    return (
      <label style={labelStyle}>
        {label}
        <input
          type="number"
          aria-label={field.name}
          disabled={disabled}
          min={field.min}
          max={field.max}
          value={typeof value === "number" ? value : ""}
          onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
          style={inputStyle}
        />
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    );
  }

  if (field.kind === "list") {
    return (
      <ListField schema={schema} field={field} value={value} disabled={disabled} onChange={onChange} />
    );
  }

  if (field.kind === "mapping") {
    const entries = Array.isArray(value) ? (value as MappingEntry[]) : [];
    return (
      <MappingSection
        title={label}
        ariaLabel={field.name}
        entries={entries}
        disabled={disabled}
        onChange={onChange}
        help={field.help}
      />
    );
  }

  if (field.kind === "object") {
    return (
      <label style={labelStyle}>
        {label} (JSON)
        <textarea
          aria-label={field.name}
          disabled={disabled}
          defaultValue={JSON.stringify(value ?? {}, null, 2)}
          onBlur={(e) => onChange(safeJson(e.target.value))}
          rows={4}
          style={{ ...inputStyle, fontFamily: "monospace" }}
        />
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </label>
    );
  }

  // expression | identifier | text | pointer -> single-line text input.
  return (
    <label style={labelStyle}>
      {label}
      <input
        aria-label={field.name}
        disabled={disabled}
        value={typeof value === "string" ? value : ""}
        onChange={(e) => onChange(e.target.value)}
        style={inputStyle}
      />
      {field.help && <span style={helpStyle}>{field.help}</span>}
    </label>
  );
}

// A list field: closed-option lists (allowed_actions, join modes) render as checkboxes;
// free lists (join branches) render as one-value-per-line text.
function ListField({
  schema,
  field,
  value,
  disabled,
  onChange,
}: {
  schema: NodeSchema;
  field: NodeFieldSchema;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const label = `${field.name}${field.required ? " *" : ""}`;
  const selected = Array.isArray(value) ? value.map(String) : [];
  const options = fieldOptions(schema, field);
  if (options.length > 0) {
    const toggle = (opt: string, on: boolean) => {
      const next = on ? [...selected, opt] : selected.filter((v) => v !== opt);
      onChange(next);
    };
    return (
      <fieldset style={{ ...labelStyle, border: "1px solid #262b36", borderRadius: 6, padding: 8 }}>
        <legend>{label}</legend>
        {options.map((opt) => (
          <label key={opt} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input
              type="checkbox"
              aria-label={`${field.name}:${opt}`}
              disabled={disabled}
              checked={selected.includes(opt)}
              onChange={(e) => toggle(opt, e.target.checked)}
            />
            {opt}
          </label>
        ))}
        {field.help && <span style={helpStyle}>{field.help}</span>}
      </fieldset>
    );
  }
  return (
    <label style={labelStyle}>
      {label}
      <textarea
        aria-label={field.name}
        disabled={disabled}
        value={selected.join("\n")}
        onChange={(e) =>
          onChange(
            e.target.value
              .split("\n")
              .map((v) => v.trim())
              .filter((v) => v !== ""),
          )
        }
        rows={3}
        style={{ ...inputStyle, fontFamily: "monospace" }}
      />
      <span style={helpStyle}>{field.help ?? "Her satıra bir değer."}</span>
    </label>
  );
}

// A JSON-Pointer mapping editor (from -> to rows). Used for node input/output mappings and
// for mapping config fields such as the join ``merge``.
function MappingSection({
  title,
  ariaLabel,
  entries,
  disabled,
  onChange,
  help,
}: {
  title: string;
  ariaLabel: string;
  entries: MappingEntry[];
  disabled: boolean;
  onChange: (entries: MappingEntry[]) => void;
  help?: string;
}) {
  const setEntry = (index: number, patch: Partial<MappingEntry>) => {
    onChange(entries.map((e, i) => (i === index ? { ...e, ...patch } : e)));
  };
  const removeEntry = (index: number) => onChange(entries.filter((_, i) => i !== index));
  const addEntry = () => onChange([...entries, { from: "", to: "" }]);
  return (
    <fieldset
      aria-label={ariaLabel}
      style={{ ...labelStyle, border: "1px solid #262b36", borderRadius: 6, padding: 8 }}
    >
      <legend>{title}</legend>
      {entries.map((entry, index) => (
        <div key={index} style={{ display: "flex", gap: 4, marginBottom: 4 }}>
          <input
            aria-label={`${ariaLabel}.${index}.from`}
            placeholder="from (/...)"
            disabled={disabled}
            value={entry.from}
            onChange={(e) => setEntry(index, { from: e.target.value })}
            style={{ ...inputStyle, marginTop: 0 }}
          />
          <input
            aria-label={`${ariaLabel}.${index}.to`}
            placeholder="to (/...)"
            disabled={disabled}
            value={entry.to}
            onChange={(e) => setEntry(index, { to: e.target.value })}
            style={{ ...inputStyle, marginTop: 0 }}
          />
          {!disabled && (
            <button
              type="button"
              aria-label={`${ariaLabel}.${index}.remove`}
              onClick={() => removeEntry(index)}
              style={smallRemoveStyle}
            >
              ×
            </button>
          )}
        </div>
      ))}
      {!disabled && (
        <button type="button" onClick={addEntry} style={smallAddStyle}>
          + eşleme ekle
        </button>
      )}
      {help && <span style={helpStyle}>{help}</span>}
    </fieldset>
  );
}

// A node-level retry_policy editor. retry_on/idempotent are fixed to the only values the
// compiler accepts (["transient"] / true); the author sets bounded attempts/backoff.
function RetrySection({
  policy,
  limits,
  disabled,
  onChange,
}: {
  policy: RetryPolicy | undefined;
  limits: NonNullable<NodeSchema["retry_policy"]>;
  disabled: boolean;
  onChange: (policy: RetryPolicy | undefined) => void;
}) {
  const enabled = policy !== undefined;
  const toggle = (on: boolean) => {
    onChange(
      on
        ? {
            max_attempts: limits.max_attempts.min,
            backoff_seconds: limits.backoff_seconds.min,
            retry_on: ["transient"],
            idempotent: true,
          }
        : undefined,
    );
  };
  return (
    <fieldset
      aria-label="retry_policy"
      style={{ ...labelStyle, border: "1px solid #262b36", borderRadius: 6, padding: 8 }}
    >
      <legend>Yeniden deneme politikası</legend>
      <label style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <input
          type="checkbox"
          aria-label="retry_enabled"
          disabled={disabled}
          checked={enabled}
          onChange={(e) => toggle(e.target.checked)}
        />
        Etkin (yalnızca transient + idempotent)
      </label>
      {enabled && policy && (
        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          <label style={{ flex: 1 }}>
            max_attempts
            <input
              type="number"
              aria-label="retry_max_attempts"
              disabled={disabled}
              min={limits.max_attempts.min}
              max={limits.max_attempts.max}
              value={policy.max_attempts}
              onChange={(e) => onChange({ ...policy, max_attempts: Number(e.target.value) })}
              style={inputStyle}
            />
          </label>
          <label style={{ flex: 1 }}>
            backoff_seconds
            <input
              type="number"
              aria-label="retry_backoff_seconds"
              disabled={disabled}
              min={limits.backoff_seconds.min}
              max={limits.backoff_seconds.max}
              value={policy.backoff_seconds}
              onChange={(e) => onChange({ ...policy, backoff_seconds: Number(e.target.value) })}
              style={inputStyle}
            />
          </label>
        </div>
      )}
    </fieldset>
  );
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const panelStyle: React.CSSProperties = {
  padding: 14,
  overflowY: "auto",
};
const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  color: "#a9b4c4",
  marginBottom: 12,
};
const inputStyle: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 4,
  padding: "6px 8px",
  borderRadius: 6,
  border: "1px solid #333a49",
  background: "#0f1115",
  color: "#e6e6e6",
};
const helpStyle: React.CSSProperties = { display: "block", color: "#6b7280", marginTop: 3 };
const removeStyle: React.CSSProperties = {
  marginTop: 8,
  padding: "6px 10px",
  borderRadius: 6,
  border: "1px solid #7f1d1d",
  background: "#2a1417",
  color: "#fca5a5",
  cursor: "pointer",
};
const smallRemoveStyle: React.CSSProperties = {
  border: "1px solid #7f1d1d",
  background: "#2a1417",
  color: "#fca5a5",
  borderRadius: 6,
  cursor: "pointer",
  padding: "0 8px",
};
const smallAddStyle: React.CSSProperties = {
  border: "1px solid #333a49",
  background: "#222835",
  color: "#cbd5e1",
  borderRadius: 6,
  cursor: "pointer",
  padding: "4px 8px",
  fontSize: 12,
};
const gatedStyle: React.CSSProperties = {
  border: "1px solid #78591c",
  background: "#2a2410",
  color: "#facc15",
  borderRadius: 6,
  padding: 8,
  fontSize: 12,
  marginBottom: 10,
};
