type GovernedProfileType = "chunking_profile" | "retrieval_profile";

export function defaultGovernedProfileBody(type: GovernedProfileType): Record<string, unknown> {
  if (type === "chunking_profile") {
    return {
      api_version: "agenthub/chunking/v1",
      kind: "ChunkingProfile",
      strategy: "tokens",
      size: 800,
      overlap: 80,
      max_chunks: 1000,
    };
  }
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

export function GovernedProfileEditor({ type, body, onChange, readOnly = false }: {
  type: GovernedProfileType;
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

  if (type === "chunking_profile") {
    return <fieldset disabled={readOnly} style={fieldsetStyle}>
      <legend>Parçalama ayarları</legend>
      <p style={hintStyle}><code>agenthub/chunking/v1</code> · alanlar canonical validator ile doğrulanır.</p>
      <label>Strateji
        <select aria-label="Parçalama stratejisi" value={String(body.strategy ?? "tokens")}
          onChange={(event) => setValue("strategy", event.target.value)}>
          {(["characters", "tokens", "headings", "pages", "tables"] as const).map((value) =>
            <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label>Parça boyutu
        <input aria-label="Parça boyutu" type="number" min={100} max={8000}
          value={Number(body.size ?? 800)}
          onChange={(event) => setValue("size", Number(event.target.value))} />
      </label>
      <label>Örtüşme
        <input aria-label="Parça örtüşmesi" type="number" min={0}
          value={Number(body.overlap ?? 0)}
          onChange={(event) => setValue("overlap", Number(event.target.value))} />
      </label>
      <label>En fazla parça
        <input aria-label="En fazla parça" type="number" min={1}
          value={Number(body.max_chunks ?? 1000)}
          onChange={(event) => setValue("max_chunks", Number(event.target.value))} />
      </label>
    </fieldset>;
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
