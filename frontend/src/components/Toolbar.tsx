import { useRef, useState } from "react";

import type { BuilderController } from "../useBuilder";

// Top toolbar: workflow id, validate/save/publish, and status. Validation and publishing
// are backend round-trips; the dirty flag and read-only badge reflect client/server state
// but never gate the server's own authorization.
export function Toolbar({
  builder,
  draftName,
  busy,
  onAction,
}: {
  builder: BuilderController;
  draftName: string;
  busy: boolean;
  onAction: (
    action: "validate" | "save" | "publish" | "publishAndVerify",
    versionDescription?: string,
  ) => void;
}) {
  const { readOnly, isDirty, diagnostics } = builder;
  const [versionDescription, setVersionDescription] = useState("");
  const [versionError, setVersionError] = useState("");
  const versionDescriptionRef = useRef<HTMLInputElement>(null);
  function requireVersionDescription(): boolean {
    if (!versionDescription.trim()) {
      setVersionError("Bu sürümde nelerin değiştiğini yazın.");
      versionDescriptionRef.current?.focus();
      return false;
    }
    setVersionError("");
    return true;
  }
  return (
    <div style={{ borderBottom: "1px solid #262b36" }}>
      <div className="ah-builder-toolbar-row">
        <strong>{draftName}</strong>
        <label style={{ fontSize: 12, color: "#8b95a7" }}>
          workflow ID
          <input
            aria-label="workflow id"
            value={builder.workflowId}
            disabled={readOnly}
            onChange={(e) => builder.setWorkflowId(e.target.value)}
            style={{
              marginLeft: 6,
              padding: "4px 8px",
              borderRadius: 6,
              border: "1px solid #333a49",
              background: "#0f1115",
              color: "#e6e6e6",
            }}
          />
        </label>
        {readOnly && <span style={badge("#7c5e10", "#fcd34d")}>salt okunur</span>}
        {!readOnly && isDirty && <span style={badge("#334155", "#93c5fd")}>kaydedilmemiş değişiklik</span>}
        <div style={{ flex: 1 }} />
        <label style={{ fontSize: 12, color: "#8b95a7" }}>
          Exact version açıklaması
          <input
            ref={versionDescriptionRef}
            aria-label="exact version açıklaması"
            value={versionDescription}
            maxLength={1000}
            disabled={readOnly}
            onChange={(event) => {
              setVersionDescription(event.target.value);
              if (event.target.value.trim()) setVersionError("");
            }}
            placeholder="Bu sürümde ne var/değişti?"
            style={{ marginLeft: 6, minWidth: 220 }}
          />
        </label>
        <button type="button" disabled={busy} onClick={() => onAction("validate")} style={btn()}>
          Doğrula
        </button>
        <button
          type="button"
          disabled={busy || readOnly || !isDirty}
          onClick={() => onAction("save")}
          style={btn()}
        >
          Kaydet
        </button>
        <button
          type="button"
          disabled={busy || readOnly}
          onClick={() => {
            if (!requireVersionDescription()) return;
            onAction("publish", versionDescription);
          }}
          style={btn()}
        >
          Yalnızca yayımla
        </button>
        <button
          type="button"
          disabled={busy || readOnly}
          title="Yayımlar, aday sürümü hazırlar ve test sorularını çalıştırır"
          onClick={() => {
            if (!requireVersionDescription()) return;
            onAction("publishAndVerify", versionDescription);
          }}
          style={btn("#2563eb")}
        >
          Yayımla ve test et
        </button>
      </div>
      {versionError && <div role="alert" style={{ padding: "0 14px 8px", color: "#fca5a5" }}>
        {versionError}
      </div>}
      {builder.status && (
        <div style={{ padding: "0 14px 8px", color: "#8b95a7", fontSize: 13 }} role="status">
          {builder.status}
        </div>
      )}
      {diagnostics && !diagnostics.ok && (
        <div
          role="alert"
          style={{
            margin: "0 14px 10px",
            padding: "8px 12px",
            borderRadius: 7,
            background: "#3a2226",
            color: "#fca5a5",
            fontSize: 13,
          }}
        >
          {diagnostics.errors.map((e, i) => (
            <div key={i}>
              <code>{e.code}</code>: {e.message}
            </div>
          ))}
        </div>
      )}
      {diagnostics && diagnostics.ok && (
        <div
          role="status"
          style={{ margin: "0 14px 10px", padding: "8px 12px", color: "#86efac", fontSize: 13 }}
        >
          Derleme başarılı · checksum {diagnostics.compiled_checksum?.slice(0, 12)}
        </div>
      )}
    </div>
  );
}

function badge(bg: string, fg: string): React.CSSProperties {
  return { background: bg, color: fg, padding: "2px 8px", borderRadius: 999, fontSize: 12 };
}
function btn(bg = "#222835"): React.CSSProperties {
  return {
    padding: "6px 12px",
    borderRadius: 7,
    border: "1px solid #333a49",
    background: bg,
    color: "#e6e6e6",
    cursor: "pointer",
  };
}
