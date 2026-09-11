\set ON_ERROR_STOP on

-- Required psql variables: app_role, database. The login secret/certificate is configured by the
-- environment owner outside this file; no credential is accepted or persisted here.
SELECT format(
    'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
    :'app_role'
) WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_role') \gexec

ALTER ROLE :"app_role" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT CONNECT ON DATABASE :"database" TO :"app_role";
GRANT USAGE ON SCHEMA public TO :"app_role";
GRANT EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) TO :"app_role";
-- Preserve legacy deployments unless the reviewed shared-only cutover is explicit.
\if :{?legacy_vector_ddl}
\else
\set legacy_vector_ddl true
\endif
SELECT :'legacy_vector_ddl'::boolean AS allow_legacy_vector_ddl \gset
\if :allow_legacy_vector_ddl
GRANT EXECUTE ON FUNCTION agenthub_provision_index_store(bigint) TO :"app_role";
GRANT EXECUTE ON FUNCTION agenthub_drop_index_store(bigint) TO :"app_role";
\else
REVOKE EXECUTE ON FUNCTION agenthub_provision_index_store(bigint) FROM :"app_role";
REVOKE EXECUTE ON FUNCTION agenthub_drop_index_store(bigint) FROM :"app_role";
\endif

-- Identity/bootstrap and Django session/auth lookup. These tables are intentionally outside tenant
-- RLS because identity is not yet known at lookup time; application authorization remains primary.
GRANT SELECT, INSERT, UPDATE ON tenancy_organization, tenancy_organizationmembership TO :"app_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON identity_consumer, identity_consumertoken TO :"app_role";
GRANT SELECT, INSERT, UPDATE ON identity_platformresponsibilityassignment TO :"app_role";
GRANT SELECT ON auth_group, auth_permission, django_content_type TO :"app_role";
GRANT SELECT ON auth_user TO :"app_role";
GRANT UPDATE(last_login) ON auth_user TO :"app_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON django_session TO :"app_role";

-- Platform-managed profile catalogs are runtime-readable but not mutable by the app role.
GRANT SELECT ON
    orchestration_modelprofile,
    ingestion_embeddingprofile,
    ingestion_ocrprofile,
    ingestion_confluenceprofile,
    ingestion_restpullprofile,
    ingestion_mcpresourceprofile
TO :"app_role";

-- Global derived identities are populated with profile registration/migration.
-- Source creation never requires write privileges on the platform catalogs.
-- FORCE RLS permits app inserts only for tenant tool identities; global inserts are denied.
DO $connection_scope$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class WHERE oid = 'public.ingestion_connection'::regclass
        AND relrowsecurity AND relforcerowsecurity
    ) OR (SELECT count(*) FROM pg_policies WHERE schemaname = 'public'
          AND tablename = 'ingestion_connection') <> 2
    OR NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public'
        AND tablename = 'ingestion_connection' AND policyname = 'connection_read_scope'
        AND cmd = 'SELECT' AND roles::text[] = ARRAY['public'] AND permissive = 'PERMISSIVE'
        AND with_check IS NULL
        AND qual = '((organization_id IS NULL) OR agenthub_tenant_scope_contains(organization_id))'
    ) OR NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public'
        AND tablename = 'ingestion_connection' AND policyname = 'connection_tool_insert_scope'
        AND cmd = 'INSERT' AND roles::text[] = ARRAY['public'] AND permissive = 'PERMISSIVE'
        AND qual IS NULL
        AND with_check = '(((kind)::text = ''tool''::text) AND (organization_id IS NOT NULL) AND agenthub_tenant_scope_contains(organization_id))'
    ) THEN
        RAISE EXCEPTION 'CONNECTION_TENANT_SCHEMA_REQUIRED';
    END IF;
END
$connection_scope$;
GRANT SELECT, INSERT ON ingestion_connection TO :"app_role";
GRANT SELECT, INSERT, UPDATE ON ingestion_sourceconfigurationrevision TO :"app_role";
-- Resource ingestion approvals are platform-owned; runtime may only consult them.
GRANT SELECT ON ingestion_tenantmcpresourcegrant TO :"app_role";
GRANT SELECT, INSERT, UPDATE ON ingestion_resourcesnapshot, ingestion_sourcedocumentcursor
    TO :"app_role";

-- Every protected table is readable only through FORCE RLS.
GRANT SELECT ON
    agents_agentruntimecontrol,
    artifacts_artifactversion,
    builder_artifactdraft, builder_workflowdraft,
    catalog_aiproject, catalog_scenario, catalog_scenarioalias,
    documents_document, documents_documentset, documents_documentsetgrant,
    documents_documentsetmembership, documents_documentsetversion, documents_documentversion,
    documents_documentversionsummary,
    documents_scenariodocumentsetaccessrequest, documents_scenariodocumentsetbinding,
    documents_scenariodocumentsetgrant,
    evaluations_evalcaseresult, evaluations_evalrun,
    evaluations_questioncase, evaluations_questionevaluationevidence,
    evaluations_questionevaluationrun, evaluations_questionset, evaluations_questionsetversion,
    gateway_idempotencyrecord, identity_consumerbinding,
    identity_documentsetresponsibilityassignment,
    identity_organizationresponsibilityassignment,
    identity_projectresponsibilityassignment,
    identity_scenarioresponsibilityassignment,
    ingestion_chunk, ingestion_sharedvectorchunk,
    ingestion_confluencedocumentcursor, ingestion_confluencesyncrun,
    ingestion_connectorschedulepromotiontarget, ingestion_connectorsyncschedule,
    ingestion_documentocrjob, ingestion_indexeddocument, ingestion_indexversion,
    ingestion_documentsetpreparationprofile,
    ingestion_ingestionrun, ingestion_restdocumentcursor, ingestion_restpullcontract,
    ingestion_restsyncrun, ingestion_source, ingestion_tenantconfluenceprofilegrant,
    ingestion_tenantembeddingprofilegrant, ingestion_tenantocrprofilegrant,
    ingestion_tenantrestpullprofilegrant, ingestion_stagedindexbuildjob,
    ingestion_stagedindexbuildoutbox, ingestion_restsetupdraft,
    releases_releasecanary, releases_scenariorelease,
    tools_approvalrequest, tools_mcpcatalogcandidate, tools_mcpcatalogsource,
    tools_toolbinding, tools_tooldefinition, tools_toolinvocation,
    workflows_customnodedefinition, workflows_run, workflows_runevent, workflows_runwait,
    workflows_runbranch, workflows_runjoin, workflows_runchildlink,
    workflows_runcompensationentry,
    workflows_workflowversion
TO :"app_role";

-- Immutable/append-only records: create + read, never update/delete through the runtime role.
GRANT INSERT ON
    artifacts_artifactversion,
    evaluations_evalcaseresult,
    evaluations_questioncase, evaluations_questionsetversion,
    tools_toolbinding, tools_tooldefinition,
    workflows_customnodedefinition, workflows_runevent,
    workflows_workflowversion
TO :"app_role";

-- Mutable state without application delete paths. The document-plane access requests/grants and the
-- delegated operator assignments are authorization-bearing: revocation is a status change that keeps
-- who held which authority reconstructable, so DELETE is withheld deliberately.
GRANT INSERT, UPDATE ON
    agents_agentruntimecontrol,
    catalog_aiproject, catalog_scenario, catalog_scenarioalias,
    documents_scenariodocumentsetaccessrequest, documents_scenariodocumentsetgrant,
    documents_documentversionsummary,
    evaluations_evalrun, evaluations_questionevaluationevidence,
    evaluations_questionevaluationrun, evaluations_questionset,
    gateway_idempotencyrecord, identity_consumerbinding,
    identity_documentsetresponsibilityassignment,
    identity_organizationresponsibilityassignment,
    identity_projectresponsibilityassignment,
    identity_scenarioresponsibilityassignment,
    ingestion_confluencedocumentcursor, ingestion_confluencesyncrun,
    ingestion_connectorschedulepromotiontarget, ingestion_connectorsyncschedule,
    ingestion_documentocrjob, ingestion_indexversion, ingestion_ingestionrun,
    ingestion_documentsetpreparationprofile,
    ingestion_restdocumentcursor, ingestion_restpullcontract, ingestion_restsyncrun,
    ingestion_source, ingestion_tenantconfluenceprofilegrant,
    ingestion_tenantembeddingprofilegrant, ingestion_tenantocrprofilegrant,
    ingestion_tenantrestpullprofilegrant, ingestion_stagedindexbuildjob,
    ingestion_stagedindexbuildoutbox, ingestion_restsetupdraft,
    releases_releasecanary, releases_scenariorelease,
    tools_approvalrequest, tools_mcpcatalogcandidate, tools_mcpcatalogsource,
    tools_toolinvocation,
    workflows_run, workflows_runwait, workflows_runbranch, workflows_runjoin,
    workflows_runchildlink, workflows_runcompensationentry
TO :"app_role";

-- Explicitly deletable operator-owned drafts and document-plane lifecycle rows.
GRANT INSERT, UPDATE, DELETE ON
    builder_artifactdraft, builder_workflowdraft,
    documents_document, documents_documentset, documents_documentsetgrant,
    documents_documentsetmembership, documents_documentsetversion, documents_documentversion,
    documents_scenariodocumentsetbinding,
    ingestion_chunk, ingestion_connectorschedulepromotiontarget, ingestion_indexeddocument
TO :"app_role";

-- Shared vectors are immutable. DELETE is admitted only by the migration-owned
-- tenant/generation/retirement/reference trigger; runtime receives no UPDATE or DDL.
GRANT INSERT, DELETE ON ingestion_sharedvectorchunk TO :"app_role";

-- Append-only cross-plane events retain separate access semantics.
-- Executable snapshots have FORCE RLS and an immutable-row/provenance trigger.
GRANT SELECT, INSERT ON releases_scenariorevision TO :"app_role";
GRANT SELECT, INSERT, UPDATE ON releases_scenariopublication TO :"app_role";
GRANT SELECT, INSERT ON workflows_runretrievalselection, workflows_runretrievalgeneration
    TO :"app_role";
GRANT SELECT, INSERT ON evaluations_evaldatageneration TO :"app_role";
GRANT SELECT, INSERT ON audit_auditevent, observability_usageevent TO :"app_role";

-- Platform heartbeat rows carry no tenant data, endpoints or credentials.
GRANT SELECT, INSERT, UPDATE ON ingestion_ingestionworkerheartbeat TO :"app_role";

-- Inserts use table-owned sequences; this does not grant table-row visibility.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_role";
