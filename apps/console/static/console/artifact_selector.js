document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-artifact-selector]");
  if (!(form instanceof HTMLFormElement)) return;

  const typeSelect = form.querySelector("[data-artifact-type]");
  const logicalSelect = form.querySelector("[data-logical-artifact]");
  const versionSelect = form.querySelector("[data-exact-version]");
  const roleSelect = form.querySelector("[data-manifest-role]");
  const addButton = form.querySelector("[data-add-artifact]");
  const compileButton = form.querySelector("[data-compile-release]");
  const selectedContainer = form.querySelector("[data-selected-artifacts]");
  const emptySelection = form.querySelector("[data-empty-selection]");
  const typeDescription = form.querySelector("[data-artifact-type-description]");
  const logicalDescription = form.querySelector("[data-logical-description]");
  const versionDescription = form.querySelector("[data-version-description]");
  const errorBox = form.querySelector("[data-selector-error]");
  if (
    !(typeSelect instanceof HTMLSelectElement) ||
    !(logicalSelect instanceof HTMLSelectElement) ||
    !(versionSelect instanceof HTMLSelectElement) ||
    !(roleSelect instanceof HTMLSelectElement) ||
    !(addButton instanceof HTMLButtonElement) ||
    !(compileButton instanceof HTMLButtonElement) ||
    !(selectedContainer instanceof HTMLElement)
  ) return;

  const optionsUrl = form.dataset.optionsUrl;
  if (!optionsUrl) return;
  const selectedIds = new Set();
  let typeOptions = [];
  let logicalOptions = [];
  let exactPayload = null;

  const showError = (message) => {
    if (!(errorBox instanceof HTMLElement)) return;
    errorBox.hidden = !message;
    errorBox.textContent = message;
  };

  const fillSelect = (select, placeholder, options, valueKey = "value", labelKey = "label") => {
    select.replaceChildren();
    const placeholderOption = document.createElement("option");
    placeholderOption.value = "";
    placeholderOption.textContent = placeholder;
    select.append(placeholderOption);
    for (const item of options) {
      const option = document.createElement("option");
      option.value = String(item[valueKey]);
      option.textContent = String(item[labelKey]);
      select.append(option);
    }
    select.disabled = options.length === 0;
  };

  const load = async (params = {}) => {
    const url = new URL(optionsUrl, window.location.origin);
    for (const [key, value] of Object.entries(params)) {
      if (value) url.searchParams.set(key, value);
    }
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error("Artifact seçenekleri yüklenemedi.");
    return response.json();
  };

  const resetVersion = () => {
    exactPayload = null;
    fillSelect(versionSelect, "Önce logical artifact seçin", []);
    fillSelect(roleSelect, "Önce version seçin", []);
    addButton.disabled = true;
    if (versionDescription instanceof HTMLElement) {
      versionDescription.textContent = "Exact immutable sürümün içeriği/değişikliği, checksum ve dependency etkisi.";
    }
  };

  typeSelect.addEventListener("change", async () => {
    showError("");
    resetVersion();
    fillSelect(logicalSelect, "Logical artifact yükleniyor…", []);
    const selectedType = typeOptions.find((item) => item.value === typeSelect.value);
    if (typeDescription instanceof HTMLElement) {
      typeDescription.textContent = selectedType?.description || "";
    }
    if (!typeSelect.value) return;
    try {
      const payload = await load({ artifact_type: typeSelect.value });
      logicalOptions = payload.options || [];
      fillSelect(logicalSelect, "Logical artifact seçin", logicalOptions);
    } catch (error) {
      showError(String(error));
    }
  });

  logicalSelect.addEventListener("change", async () => {
    showError("");
    resetVersion();
    const logical = logicalOptions.find((item) => item.value === logicalSelect.value);
    if (logicalDescription instanceof HTMLElement) {
      logicalDescription.textContent = logical?.description || "";
    }
    if (!logicalSelect.value) return;
    try {
      exactPayload = await load({
        artifact_type: typeSelect.value,
        logical_id: logicalSelect.value,
      });
      const versions = (exactPayload.options || []).map((item) => ({
        ...item,
        label: `v${item.version} · ${String(item.checksum).slice(0, 12)}`,
      }));
      fillSelect(versionSelect, "Exact version seçin", versions, "id", "label");
      fillSelect(
        roleSelect,
        "Manifest rolü seçin",
        (exactPayload.roles || []).map((role) => ({ value: role, label: role })),
      );
    } catch (error) {
      showError(String(error));
    }
  });

  versionSelect.addEventListener("change", () => {
    const version = exactPayload?.options?.find(
      (item) => String(item.id) === versionSelect.value,
    );
    if (versionDescription instanceof HTMLElement) {
      versionDescription.textContent = version
        ? `${version.description} · checksum ${version.checksum} · ${version.pinned_release_count} release tarafından pinli`
        : "";
    }
    roleSelect.disabled = !version;
    addButton.disabled = !version || !roleSelect.value || selectedIds.has(String(version.id));
  });

  roleSelect.addEventListener("change", () => {
    addButton.disabled = !versionSelect.value || !roleSelect.value ||
      selectedIds.has(versionSelect.value);
  });

  addButton.addEventListener("click", () => {
    const version = exactPayload?.options?.find(
      (item) => String(item.id) === versionSelect.value,
    );
    if (!version || !roleSelect.value || selectedIds.has(String(version.id))) return;
    selectedIds.add(String(version.id));

    const row = document.createElement("div");
    row.className = "access-row";
    const summary = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${typeSelect.value} → ${logicalSelect.value} → v${version.version}`;
    const detail = document.createElement("p");
    detail.className = "muted";
    detail.textContent = `${exactPayload.logical_description} · ${version.description} · rol ${roleSelect.value} · checksum ${String(version.checksum).slice(0, 12)}`;
    summary.append(title, detail);

    const artifactInput = document.createElement("input");
    artifactInput.type = "hidden";
    artifactInput.name = "artifact_ids";
    artifactInput.value = String(version.id);
    const roleInput = document.createElement("input");
    roleInput.type = "hidden";
    roleInput.name = `role_${version.id}`;
    roleInput.value = roleSelect.value;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button danger ghost";
    remove.textContent = "Kaldır";
    remove.addEventListener("click", () => {
      selectedIds.delete(String(version.id));
      row.remove();
      compileButton.disabled = selectedIds.size === 0;
      if (emptySelection instanceof HTMLElement) emptySelection.hidden = selectedIds.size > 0;
      versionSelect.dispatchEvent(new Event("change"));
    });
    row.append(summary, artifactInput, roleInput, remove);
    selectedContainer.append(row);
    if (emptySelection instanceof HTMLElement) emptySelection.hidden = true;
    compileButton.disabled = false;
    addButton.disabled = true;
  });

  load()
    .then((payload) => {
      typeOptions = payload.options || [];
      fillSelect(typeSelect, "Artifact type seçin", typeOptions);
    })
    .catch((error) => showError(String(error)));
});
