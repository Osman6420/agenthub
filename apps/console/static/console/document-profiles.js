function syncProfileInspector(field) {
  const select = field.querySelector("select");
  const inspector = field.querySelector("[data-profile-inspector]");
  if (!(select instanceof HTMLSelectElement) || !(inspector instanceof HTMLElement)) return;

  const selectedId = select.value;
  let visible = false;
  inspector.querySelectorAll("[data-profile-option]").forEach((option) => {
    if (!(option instanceof HTMLElement)) return;
    const matches = option.dataset.profileOption === selectedId;
    option.hidden = !matches;
    visible ||= matches;
  });
  const empty = inspector.querySelector("[data-profile-empty]");
  if (empty instanceof HTMLElement) empty.hidden = visible;
}

document.querySelectorAll("[data-profile-field]").forEach((field) => {
  if (!(field instanceof HTMLElement)) return;
  const select = field.querySelector("select");
  if (!(select instanceof HTMLSelectElement)) return;
  syncProfileInspector(field);
  select.addEventListener("change", () => syncProfileInspector(field));
});

document.querySelectorAll("[data-document-profile-editor][data-current-profile-id]")
  .forEach((editor) => {
    if (!(editor instanceof HTMLElement)) return;
    const select = editor.querySelector("[data-profile-model]");
    if (select instanceof HTMLSelectElement) select.value = editor.dataset.currentProfileId ?? "";
  });

function editorPayload(editor) {
  const artifactType = editor.dataset.artifactType ?? "";
  const versionDescription = editor.querySelector("[data-profile-version-description]");
  if (!(versionDescription instanceof HTMLInputElement) || !versionDescription.value.trim()) {
    throw new Error("Bu sürümde ne değiştiğini yazın.");
  }
  let body;
  const prompt = editor.querySelector("[data-profile-prompt]");
  const model = editor.querySelector("[data-profile-model]");
  const jsonBody = editor.querySelector("[data-profile-json]");
  if (prompt instanceof HTMLTextAreaElement) {
    body = { template: prompt.value };
  } else if (model instanceof HTMLSelectElement) {
    if (!model.value) throw new Error("Aktif bir platform model profili seçin.");
    body = { profile_id: model.value };
  } else if (jsonBody instanceof HTMLTextAreaElement) {
    try {
      body = JSON.parse(jsonBody.value);
    } catch {
      throw new Error("Profil içeriği geçerli bir JSON nesnesi olmalıdır.");
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new Error("Profil içeriği geçerli bir JSON nesnesi olmalıdır.");
    }
  } else {
    throw new Error("Profil içeriği bulunamadı.");
  }
  const payload = {
    artifact_type: artifactType,
    version_description: versionDescription.value.trim(),
    body,
  };
  const sourceId = Number(editor.dataset.sourceArtifactId ?? "0");
  if (Number.isSafeInteger(sourceId) && sourceId > 0) {
    payload.source_artifact_id = sourceId;
  } else {
    const logicalId = editor.querySelector("[data-profile-logical-id]");
    const logicalDescription = editor.querySelector("[data-profile-logical-description]");
    if (!(logicalId instanceof HTMLInputElement) || !logicalId.value.trim()) {
      throw new Error("Logical ID girin.");
    }
    if (!(logicalDescription instanceof HTMLInputElement) || !logicalDescription.value.trim()) {
      throw new Error("Kalıcı amacı yazın.");
    }
    payload.logical_id = logicalId.value.trim();
    payload.logical_description = logicalDescription.value.trim();
  }
  return payload;
}

function profileErrorMessage(code) {
  const messages = {
    artifact_unchanged: "İçerik değişmedi; mevcut exact sürümü kullanabilirsiniz.",
    artifact_invalid: "Profil alanları canonical sözleşmeye uymuyor.",
    logical_id_exists: "Bu logical ID zaten var; mevcut sürümü açıp düzenleyin.",
    logical_id_invalid: "Logical ID küçük harf, sayı, nokta, tire veya alt çizgi içermelidir.",
    logical_description_invalid: "Kalıcı amacı 1-1000 karakter arasında yazın.",
    model_profile_unavailable: "Seçilen platform model profili aktif değil.",
    source_artifact_unavailable: "Kaynak artifact bu doküman setinin organizasyonunda kullanılamıyor.",
    version_description_required: "Bu sürümde ne değiştiğini yazın.",
  };
  return messages[code] ?? code ?? "Profil yayımlanamadı.";
}

document.querySelectorAll("[data-document-profile-editor]").forEach((editor) => {
  if (!(editor instanceof HTMLElement)) return;
  const button = editor.querySelector("[data-profile-publish]");
  const status = editor.querySelector("[data-profile-editor-status]");
  if (!(button instanceof HTMLButtonElement) || !(status instanceof HTMLElement)) return;
  button.addEventListener("click", async () => {
    const build = document.querySelector("[data-profile-publish-url]");
    const csrf = document.querySelector("#build input[name='csrfmiddlewaretoken']");
    const url = build instanceof HTMLElement ? build.dataset.profilePublishUrl ?? "" : "";
    if (!url || !(csrf instanceof HTMLInputElement)) {
      status.textContent = "Doküman profil yayınlama bağlantısı kullanılamıyor.";
      return;
    }
    button.disabled = true;
    status.textContent = "";
    try {
      const payload = editorPayload(editor);
      const response = await fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrf.value,
        },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(profileErrorMessage(result.code));
      receivePublishedArtifact({
        kind: "artifact_published",
        artifactVersionId: result.artifact_version_id,
        artifactType: result.artifact_type,
        logicalId: result.logical_id,
        version: result.version,
        body: result.body,
      });
      status.textContent = `${result.logical_id}:v${result.version} yayımlandı ve seçildi.`;
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : "Profil yayımlanamadı.";
    } finally {
      button.disabled = false;
    }
  });
});

function receivePublishedArtifact(message) {
  if (!message || message.kind !== "artifact_published") return;
  if (!Number.isSafeInteger(message.artifactVersionId) || message.artifactVersionId < 1) return;
  if (!Number.isSafeInteger(message.version) || message.version < 1) return;
  if (typeof message.logicalId !== "string" || !message.logicalId || message.logicalId.length > 128) return;
  if (!["chunking_profile", "retrieval_profile", "prompt_template", "model_profile"].includes(
    message.artifactType,
  )) return;
  if (!message.body || typeof message.body !== "object" || Array.isArray(message.body)) return;
  let bodyText;
  try {
    bodyText = JSON.stringify(message.body, null, 2);
  } catch {
    return;
  }
  if (new TextEncoder().encode(bodyText).length > 32 * 1024) return;

  const field = [...document.querySelectorAll("[data-profile-field][data-artifact-type]")]
    .find((candidate) => candidate.dataset.artifactType === message.artifactType);
  if (!(field instanceof HTMLElement)) return;
  const select = field.querySelector("select");
  const inspector = field.querySelector("[data-profile-inspector]");
  if (!(select instanceof HTMLSelectElement) || !(inspector instanceof HTMLElement)) return;

  const id = String(message.artifactVersionId);
  let option = [...select.options].find((candidate) => candidate.value === id);
  if (!option) {
    option = document.createElement("option");
    option.value = id;
    select.appendChild(option);
  }
  option.textContent = `${message.logicalId}:v${message.version}`;

  let detail = [...inspector.querySelectorAll("[data-profile-option]")]
    .find((candidate) => candidate.dataset.profileOption === id);
  if (!detail) {
    detail = document.createElement("details");
    detail.className = "relationship-card";
    detail.dataset.profileOption = id;
    const summary = document.createElement("summary");
    const title = document.createElement("strong");
    title.textContent = `${message.logicalId}:v${message.version}`;
    summary.append(title, " · içeriği gör");
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = "Bu sekme açıkken yayımlanan yeni immutable sürüm.";
    const body = document.createElement("pre");
    body.className = "mono";
    body.style.whiteSpace = "pre-wrap";
    body.style.overflowWrap = "anywhere";
    body.textContent = bodyText;
    detail.append(summary, note, body);
    inspector.appendChild(detail);
  }

  select.value = id;
  syncProfileInspector(field);
  const status = inspector.querySelector("[data-profile-publish-status]");
  if (status instanceof HTMLElement) {
    status.textContent = `${message.logicalId}:v${message.version} seçildi; diğer profil seçimleri korundu.`;
    status.hidden = false;
  }
}

if ("BroadcastChannel" in window) {
  const artifactChannel = new BroadcastChannel("agenthub-artifact-authoring");
  artifactChannel.addEventListener("message", (event) => receivePublishedArtifact(event.data));
}
