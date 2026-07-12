import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import type { OrgOption } from "./types";

// Mount into the Django-rendered element. Configuration (API base, the operator's
// in-scope organizations) is provided by the server template — never hardcoded here.
const root = document.getElementById("agenthub-builder-root");
if (root) {
  const apiBase = root.dataset.apiBase ?? "/console/api/builder/";
  const orgsId = root.dataset.orgsId ?? "";
  let orgs: OrgOption[] = [];
  const island = orgsId ? document.getElementById(orgsId) : null;
  if (island?.textContent) {
    try {
      orgs = JSON.parse(island.textContent) as OrgOption[];
    } catch {
      orgs = [];
    }
  }
  root.innerHTML = ""; // clear the server-rendered loading fallback
  createRoot(root).render(
    <StrictMode>
      <App apiBase={apiBase} orgs={orgs} />
    </StrictMode>,
  );
}
