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
