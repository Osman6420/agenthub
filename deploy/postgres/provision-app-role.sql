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

-- Identity/bootstrap and Django session/auth lookup. These tables are intentionally outside tenant
-- RLS because identity is not yet known at lookup time; application authorization remains primary.
GRANT SELECT, INSERT, UPDATE ON tenancy_organization, tenancy_organizationmembership TO :"app_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON identity_consumer, identity_consumertoken TO :"app_role";
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
    ingestion_restpullprofile
TO :"app_role";

-- Every protected table is readable only through FORCE RLS.
GRANT SELECT ON
    agents_agentruntimecontrol,
    artifacts_artifactversion,
    builder_artifactdraft, builder_workflowdraft,
    catalog_aiproject, catalog_scenario, catalog_scenarioalias,
    documents_document, documents_documentset, documents_documentsetgrant,
    documents_documentsetmembership, documents_documentsetversion, documents_documentversion,
    documents_scenariodocumentsetaccessrequest, documents_scenariodocumentsetbinding,
    documents_scenariodocumentsetgrant,
    evaluations_evalcaseresult, evaluations_evalrun,
    gateway_idempotencyrecord, identity_consumerbinding,
    identity_documentsetmanagerassignment, identity_projectadministratorassignment,
    identity_scenarioeditorassignment,
    ingestion_chunk, ingestion_confluencedocumentcursor, ingestion_confluencesyncrun,
    ingestion_connectorschedulepromotiontarget, ingestion_connectorsyncschedule,
    ingestion_documentocrjob, ingestion_indexeddocument, ingestion_indexversion,
    ingestion_ingestionrun, ingestion_restdocumentcursor, ingestion_restpullcontract,
    ingestion_restsyncrun, ingestion_source, ingestion_tenantconfluenceprofilegrant,
    ingestion_tenantembeddingprofilegrant, ingestion_tenantocrprofilegrant,
    ingestion_tenantrestpullprofilegrant, ingestion_stagedindexbuildjob,
    ingestion_stagedindexbuildoutbox,
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
    evaluations_evalrun,
    gateway_idempotencyrecord, identity_consumerbinding,
    identity_documentsetmanagerassignment, identity_projectadministratorassignment,
    identity_scenarioeditorassignment,
    ingestion_confluencedocumentcursor, ingestion_confluencesyncrun,
    ingestion_connectorschedulepromotiontarget, ingestion_connectorsyncschedule,
    ingestion_documentocrjob, ingestion_indexversion, ingestion_ingestionrun,
    ingestion_restdocumentcursor, ingestion_restpullcontract, ingestion_restsyncrun,
    ingestion_source, ingestion_tenantconfluenceprofilegrant,
    ingestion_tenantembeddingprofilegrant, ingestion_tenantocrprofilegrant,
    ingestion_tenantrestpullprofilegrant, ingestion_stagedindexbuildjob,
    ingestion_stagedindexbuildoutbox,
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

-- Append-only cross-plane events retain separate access semantics.
GRANT SELECT, INSERT ON audit_auditevent, observability_usageevent TO :"app_role";

-- Platform heartbeat rows carry no tenant data, endpoints or credentials.
GRANT SELECT, INSERT, UPDATE ON ingestion_ingestionworkerheartbeat TO :"app_role";

-- Inserts use table-owned sequences; this does not grant table-row visibility.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_role";
