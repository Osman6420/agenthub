import { useCallback, useEffect, useState } from "react";

import { ApiError, BuilderApi } from "./api";
import { Editor } from "./Editor";
import type { BuilderInitial, Draft, NodeSchema, OrgOption } from "./types";

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
  const [active, setActive] = useState<Draft | null>(null);
  const [error, setError] = useState<string>("");
  const [newName, setNewName] = useState("");
  const [newId, setNewId] = useState("");
  const [deepLinkHandled, setDeepLinkHandled] = useState(false);

  const org = orgs.find((o) => o.slug === orgSlug);
  const canWrite = !!org?.can_write;

  const reload = useCallback(async () => {
    if (!orgSlug) return;
    setError("");
    try {
      const [s, list] = await Promise.all([api.nodeSchema(orgSlug), api.listDrafts()]);
      setSchema(s);
      setDrafts(list.drafts.filter((d) => d.organization === orgSlug));
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    }
  }, [api, orgSlug]);

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

  useEffect(() => {
    if (deepLinkHandled || !schema || !initial?.draft_id) return;
    setDeepLinkHandled(true);
    if (drafts.some((draft) => draft.id === initial.draft_id)) {
      void open(initial.draft_id);
    } else {
      setError("not_found: draft seçilen organizasyonun dışında");
    }
  }, [deepLinkHandled, drafts, initial?.draft_id, open, schema]);

  const create = useCallback(async () => {
    try {
      const draft = await api.createDraft({
        organization: orgSlug,
        name: newName,
        logical_id: newId,
        body: {},
      });
      setNewName("");
      setNewId("");
      await reload();
      setActive(draft);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : String(err));
    }
  }, [api, newName, newId, orgSlug, reload]);

  if (active && schema) {
    return (
      <div>
        <button type="button" onClick={() => setActive(null)} style={backBtn}>
          ← Draft'lar
        </button>
        <Editor api={api} schema={schema} draft={active} />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 820 }}>
      {error && (
        <div role="alert" style={errorBox}>
          {error}
        </div>
      )}
      <div className="ah-builder-org-row">
        <label style={{ color: "#8b95a7", fontSize: 13 }}>
          Organizasyon
          <select
            aria-label="organizasyon"
            value={orgSlug}
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
