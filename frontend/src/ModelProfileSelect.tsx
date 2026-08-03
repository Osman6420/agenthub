import { useEffect, useMemo, useState } from "react";

import { ApiError, BuilderApi } from "./api";
import type { ModelProfileOption } from "./types";

export function ModelProfileSelect({
  api,
  organization,
  projectId,
  scenarioId,
  value,
  onChange,
  readOnly = false,
}: {
  api: BuilderApi;
  organization: string;
  projectId: number;
  scenarioId: number;
  value: string;
  onChange: (profileId: string) => void;
  readOnly?: boolean;
}) {
  const [options, setOptions] = useState<ModelProfileOption[]>([]);
  const [status, setStatus] = useState("");
  const [limited, setLimited] = useState(false);

  useEffect(() => {
    if (readOnly) return;
    let active = true;
    void api.modelProfileOptions({
      organization,
      projectId,
      scenarioId,
      selectedProfileId: value,
    }).then((result) => {
      if (!active) return;
      setOptions(result.options);
      setLimited(result.limited);
    }).catch((error: unknown) => {
      if (active) setStatus(error instanceof ApiError ? error.code : String(error));
    });
    return () => { active = false; };
  }, [api, organization, projectId, readOnly, scenarioId, value]);

  const selected = useMemo(
    () => options.find((option) => option.profile_id === value),
    [options, value],
  );

  if (readOnly) return <div>
    <strong>Platform model profil referansı</strong>
    <div><code>{value || "—"}</code></div>
    <p>Salt okunur UUID referansı; endpoint ve secret alanları gösterilmez.</p>
  </div>;

  return <div>
    <label>Platform model profili
      <select aria-label="platform model profili" value={value}
        onChange={(event) => onChange(event.target.value)}>
        <option value="">Profil seçin</option>
        {options.map((option) => <option key={option.profile_id} value={option.profile_id}>
          {option.logical_id}:r{option.revision} · {option.provider} / {option.model}
        </option>)}
      </select>
    </label>
    {selected && <p>
      Güvenli özet: {selected.provider} / {selected.model} · en fazla {selected.max_output_tokens}
      {" "}output token. Endpoint ve secret alanları gösterilmez.
    </p>}
    {limited && <p role="status">İlk 100 aktif profil gösteriliyor; mevcut seçim ayrıca korunur.</p>}
    {status && <div role="alert">{status}</div>}
  </div>;
}
