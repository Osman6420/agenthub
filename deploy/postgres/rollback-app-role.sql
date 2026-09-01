\set ON_ERROR_STOP on

-- Required psql variables: app_role, database. Rollback disables login first, terminates no
-- sessions automatically, and preserves the role for audit/forensics. Connection draining and
-- DATABASE_URL rollback happen in the deployment controller before this script.
ALTER ROLE :"app_role" NOLOGIN;
REVOKE CONNECT ON DATABASE :"database" FROM :"app_role";
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM :"app_role";
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM :"app_role";
REVOKE EXECUTE ON FUNCTION agenthub_tenant_scope_contains(bigint) FROM :"app_role";
REVOKE EXECUTE ON FUNCTION agenthub_provision_index_store(bigint) FROM :"app_role";
REVOKE EXECUTE ON FUNCTION agenthub_drop_index_store(bigint) FROM :"app_role";
REVOKE USAGE ON SCHEMA public FROM :"app_role";

-- Do not DROP ROLE automatically. Drop is a separate destructive operation after session,
-- ownership, dependency and audit review.
