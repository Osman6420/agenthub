# Threat Model: scenario-and-document-authoring-ux

Proportional model. This task adds one authoring action (branching a document-set version),
tightens the release traffic gate, changes what error messages disclose, and moves profile
authoring from raw JSON into rendered fields. It adds no dependency, no egress and no new
authorization surface. The dominant risks are the new gate being wrong in either direction,
over-disclosure through error messages and evaluation evidence, and the client form drifting
from the validator.

## Assets

- The promotion/canary gate: the only automated barrier between a candidate and consumers.
- Published document-set versions: immutable snapshots that pinned releases resolve against.
- Test questions, generated answers and assertion outcomes (tenant-confidential).
- Governed profile artifacts (chunking, retrieval) and their immutable identities.

## Actors

- Scenario Editor: writes questions, publishes candidates, runs evaluations.
- Release Manager: the only role that may change what traffic sees.
- Document-set Manager: uploads, branches and publishes set versions, configures preparation.
- A consumer calling the public gateway, who cannot see how the answer was produced.
- A hostile or careless cross-tenant operator probing the new routes.

## Entry points

- `POST /console/document-set-versions/<pk>/branch/` (session/LDAP + CSRF, tenant-scoped).
- `POST /console/document-sets/id/<uuid>/profile-artifacts/` with `display_name` instead of a
  caller-chosen `logical_id`.
- `POST /console/scenarios/id/<uuid>/{ask,promote,test-questions}/`.
- `POST /v1/{responses,chat/completions}` — unchanged surface, changed failure messages.

## Trust boundaries

- Rendered profile form ↔ validator: the client assembles a body from fields; the server still
  decides. The form is a convenience, never the authority.
- Evaluation ↔ served traffic: an evaluation may execute a candidate; promotion is what
  exposes it, and that is where the provider check sits.
- Author draft ↔ published snapshot: branching reads a frozen version and writes a new draft.
  The source is never mutated.

## Data classifications

- Assertion outcomes now carry the expected literal. That is author content, so it renders
  only for a viewer who may already see questions and answers (`can_view_content`).
- Gateway error messages: condition only — no internal state, identifiers, dependency names
  or configuration values. `RUN_RUNTIME_SUSPENDED` says the runtime is not accepting runs, not
  which control suspended it or why.
- Derived logical ids embed the document-set logical id and a slug of the operator's name.
  Both are already tenant-visible; no secret or personal data enters an identifier.

## Authentication

Unchanged. Console session/LDAP + CSRF on every new action; no new anonymous or bearer route.

## Authorization

Deny by default, server-side:

- Branching requires `can_manage_documents` for that document set — the same gate as creating
  a version or adding a member.
- Deriving a profile identity does not widen `publish_document_profile_artifact`: the same
  authorization runs, only the identity argument is server-supplied.
- Promotion and canary remain Release Manager only; the provider check is an *additional*
  refusal on that path, never a relaxation.
- Reading the last run's answers reuses `_run_content_access`, the same `SCENARIO_TEST`
  decision the report page makes.

## Tenant isolation

`_scoped_set_version` and `_scoped_scenario` bind every new view to the operator's
organization; a foreign version returns 404 without disclosing existence (tested).
`_derive_profile_identity` checks collisions within the set's organization only, so a
neighbouring tenant's identifiers neither leak nor constrain.

## External systems

None added. The provider check *reduces* live egress: it refuses to serve a scenario that has
no configured provider.

## Abuse cases

- Promoting a scenario that answers from the deterministic stub, so consumers receive
  plausible text no model produced — the case this task closes.
- The inverse: the new gate blocking a legitimate promotion in an environment where a provider
  *is* configured. Guarded by keying only on `RUNTIME_MODEL_PROVIDER` and only for workflows
  that actually contain `generate`/`agent_loop`.
- Branching in a loop to exhaust version numbers or storage — bounded by the single-open-draft
  rule.
- Two operators branching concurrently and racing to publish — the draft check runs under
  `select_for_update` on the document set.
- Harvesting another tenant's expected answers through the assertion `value` now present in
  evidence.
- Error messages used to fingerprint runtime state (which control is suspended, what limits
  apply).
- A crafted `display_name` steering the derived logical id into another artifact's identity.

## Failure cases

- Provider unset on a generating release: promotion fails closed with
  `MODEL_PROVIDER_NOT_CONFIGURED`, audited as a denial.
- An unmapped `WorkflowRequestError` code: generic 400, never a specific wrong message.
- Branch while a draft is open: refused with a named reason, no partial state.
- A conditional profile field left in the body outside hybrid: the validator rejects it, so the
  client removes hidden fields before publishing.

## Logging and audit risks

- `documents.set_version.branch` audits the source version and the copied member count — no
  document content.
- Promotion denials audit the reason code, as the existing gate denials do.
- Error messages are returned to callers but not logged with request bodies.
- The assertion `value` is persisted in evidence and covered by the existing evaluation
  retention/purge windows.

## Mitigations

- The provider check sits on the shared `_assert_release_gate`, so promotion and canary cannot
  diverge, and it is scoped to generating workflows only.
- Form choices and bounds are imported from `governed_dsl`, and a test asserts the offered
  defaults validate, every offered choice is allowed, and the stated bounds are the enforced
  ones — the form cannot drift from the rules it describes.
- The expected literal is rendered only under `can_view_content`.
- Error messages are a fixed table of safe strings, reviewed per code.
- Derived identities are collision-checked within the tenant and suffixed until unique.
- Branching copies membership through the audited `add_document_to_set_version`, so the new
  draft's provenance is the same as any other draft's.

## Residual risks

- `MODEL_PROVIDER_NOT_CONFIGURED` keys on a deployment-wide setting, not on whether the pinned
  model profile is actually reachable. A configured but broken provider still promotes; that
  failure surfaces at request time.
- The staged-index rejection is instrumented but the original report is still unreproduced.
- Upstream provider failures remain collapsed into one code and misclassified as transient
  (carried over, unapproved).
- The generated frontend bundle is gitignored; a stale bundle can hide a shipped fix, as it did
  for the Studio back link. Only `npm --prefix frontend run build` prevents it.

## Required security tests

- A generating release with no provider is refused on **both** promote and canary, audited,
  and the same release promotes once a provider is configured — asserted.
- A non-generating release needs no provider — asserted.
- Cross-tenant branch returns 404 — asserted.
- Branching refuses while a draft is open and leaves exactly one draft — asserted.
- Offered defaults validate; offered choices and bounds equal the enforced ones — asserted.
- Every generated curl example carries `Idempotency-Key` and parses as JSON — asserted.
- A suspended runtime is not reported as a header problem — asserted.
- **Not covered:** cross-tenant probing through a real browser session, and rendered
  affordance parity for the new controls (browser gate).
