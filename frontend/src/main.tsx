import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import type { BuilderInitial, OrgOption } from "./types";
import "./builder.css";

// Mount into the Django-rendered element. Configuration (API base, the operator's
// in-scope organizations) is provided by the server template — never hardcoded here.
const root = document.getElementById("agenthub-builder-root");
if (root) {
  const apiBase = root.dataset.apiBase ?? "/console/api/builder/";
  const orgsId = root.dataset.orgsId ?? "";
  const initialId = root.dataset.initialId ?? "";
  let orgs: OrgOption[] = [];
  let initial: BuilderInitial = {};
  const island = orgsId ? document.getElementById(orgsId) : null;
  if (island?.textContent) {
    try {
      orgs = JSON.parse(island.textContent) as OrgOption[];
    } catch {
      orgs = [];
    }
  }
  const initialIsland = initialId ? document.getElementById(initialId) : null;
  if (initialIsland?.textContent) {
    try {
      initial = JSON.parse(initialIsland.textContent) as BuilderInitial;
    } catch {
      initial = {};
    }
  }
  root.innerHTML = ""; // clear the server-rendered loading fallback
  createRoot(root).render(
    <StrictMode>
      <App apiBase={apiBase} orgs={orgs} initial={initial} />
    </StrictMode>,
  );
}
