// Chunking profiles are authored on the document-set page, never in Studio.
type GovernedProfileType = "retrieval_profile";

export function defaultGovernedProfileBody(_type: GovernedProfileType): Record<string, unknown> {
  return {
    api_version: "agenthub/retrieval/v1",
    kind: "RetrievalProfile",
    mode: "hybrid",
    top_k: 8,
    score_threshold: 0,
    vector_weight: 0.7,
    keyword_weight: 0.3,
  };
}

export function GovernedProfileEditor({ body, onChange, readOnly = false }: {
  type?: GovernedProfileType;
  body: Record<string, unknown>;
  onChange: (body: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  function setValue(key: string, value: unknown) {
    onChange({ ...body, [key]: value });
  }

  function setOptionalNumber(key: string, value: string) {
    if (!value) {
      const next = { ...body };
      delete next[key];
      onChange(next);
      return;
    }
    setValue(key, Number(value));
  }

  const mode = String(body.mode ?? "hybrid");
  return <fieldset disabled={readOnly} style={fieldsetStyle}>
    <legend>Arama ayarları</legend>
    <p style={hintStyle}><code>agenthub/retrieval/v1</code> · alanlar canonical validator ile doğrulanır.</p>
    <label>Arama modu
      <select aria-label="Arama modu" value={mode} onChange={(event) => {
        const next: Record<string, unknown> = { ...body, mode: event.target.value };
        if (event.target.value === "hybrid") {
          next.vector_weight = 0.7;
          next.keyword_weight = 0.3;
        } else {
          delete next.vector_weight;
          delete next.keyword_weight;
        }
        onChange(next);
      }}>
        <option value="keyword">keyword</option>
        <option value="vector">vector</option>
        <option value="hybrid">hybrid</option>
      </select>
    </label>
    <label>Sonuç sayısı
      <input aria-label="Arama sonuç sayısı" type="number" min={1} max={50}
        value={Number(body.top_k ?? 8)}
        onChange={(event) => setValue("top_k", Number(event.target.value))} />
    </label>
    <label>Skor eşiği
      <input aria-label="Arama skor eşiği" type="number" min={0} max={1} step={0.01}
        value={Number(body.score_threshold ?? 0)}
        onChange={(event) => setValue("score_threshold", Number(event.target.value))} />
    </label>
    {mode === "hybrid" && <>
      <label>Vektör ağırlığı
        <input aria-label="Vektör ağırlığı" type="number" min={0} max={1} step={0.01}
          value={Number(body.vector_weight ?? 0.7)}
          onChange={(event) => setValue("vector_weight", Number(event.target.value))} />
      </label>
      <label>Kelime ağırlığı
        <input aria-label="Kelime ağırlığı" type="number" min={0} max={1} step={0.01}
          value={Number(body.keyword_weight ?? 0.3)}
          onChange={(event) => setValue("keyword_weight", Number(event.target.value))} />
      </label>
    </>}
    <label>Reranker profil referansı (isteğe bağlı)
      <input aria-label="Reranker profil referansı"
        value={typeof body.reranker_profile_ref === "string" ? body.reranker_profile_ref : ""}
        onChange={(event) => {
          const next = { ...body };
          if (event.target.value) next.reranker_profile_ref = event.target.value;
          else delete next.reranker_profile_ref;
          onChange(next);
        }} />
    </label>
    <label>Özetlenecek belge sayısı (isteğe bağlı)
      <input aria-label="Özetlenecek belge sayısı" type="number" min={1} max={50}
        value={body.summary_document_top_k === undefined ? "" : Number(body.summary_document_top_k)}
        onChange={(event) => setOptionalNumber("summary_document_top_k", event.target.value)} />
    </label>
    {body.summary_document_top_k !== undefined && <label>Belge başına en fazla parça
      <input aria-label="Belge başına en fazla parça" type="number" min={1} max={10}
        value={Number(body.max_chunks_per_document ?? 3)}
        onChange={(event) => setValue("max_chunks_per_document", Number(event.target.value))} />
    </label>}
    {body.metadata_filter !== undefined && <p role="note" style={hintStyle}>
      Mevcut metadata filtresi korunur; filtre oluşturucu Part 2B’de eklenecek.
    </p>}
  </fieldset>;
}

const fieldsetStyle: React.CSSProperties = {
  display: "grid",
  gap: 10,
  margin: "10px 0",
  padding: 12,
  border: "1px solid #334155",
  borderRadius: 7,
};

const hintStyle: React.CSSProperties = { color: "#8b95a7", margin: 0, fontSize: 13 };
