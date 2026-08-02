# Threat Model: Phase 2.9 Part 7 Browser and Quality Closure

## Assets and actors

Canonical local/production data, synthetic browser fixtures and credentials, operator sessions,
document content, release/index/run metadata, request/trace IDs, screenshots/logs and CI artifacts.
Actors include authorized role fixtures, same-tenant foreign-scope users, cross-tenant users,
anonymous clients, malicious page content and accidental test operators.

## Abuse and failure cases

- A launcher points at the developer's canonical PostgreSQL database and flushes/seeds it.
- Screenshots, HAR, console logs or failure messages persist passwords, cookies, tokens or content.
- UI hiding is mistaken for authorization and direct URLs still expose/mutate foreign resources.
- A dashboard count or action link discloses tenant-wide decision state to an exact viewer even when
  the corresponding task surface is absent from responsibility-aware navigation.
- Browser state leaks between roles, tests depend on order, or asynchronous waits make CI flaky.
- Provider-disabled state triggers external egress or includes secret/profile configuration.
- A typing/format cleanup weakens a check or changes runtime behavior to make CI green.

## Controls

- Browser database name has an explicit test-only prefix; launcher rejects canonical names,
  non-loopback hosts and missing opt-in. CI database is disposable.
- One isolated browser context per role; cookies/storage are never logged or reused across roles.
- Failure evidence includes only a bounded viewport screenshot, safe URL path, role label,
  request ID and redacted console/network categories; no HAR/video/DOM dump/body/header values.
- Every visible/hidden assertion is paired with a direct route/mutation status and no-state-change
  assertion where applicable. Existing PostgreSQL/RLS tests remain required.
- Dashboard sections and their counts use the same capability/scope predicates as their destination
  surfaces; unauthorized roles receive neither the count nor the action link.
- All network/provider behavior stays disabled unless the synthetic fixture uses an existing local
  deterministic adapter; no external endpoint or credential is configured.
- Type/format changes receive full diff review and the same complete backend/frontend gates.

## Residual risk

Rendering and focus can differ across browsers/OS scaling; Chromium automation cannot replace
human assistive-technology review. CI browser installation is an external package availability
dependency. The manual pass and any environment limitation must be recorded, never inferred from
automated success.
