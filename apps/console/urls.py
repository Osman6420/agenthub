"""Operator console URLs (all under ``/console/``)."""

from __future__ import annotations

from django.contrib.auth import views as auth_views
from django.urls import path

from apps.console import (
    access_views,
    data_access_views,
    mcp_schedule_views,
    mcp_source_views,
    preparation_settings_views,
    publication_views,
    rest_setup_entry,
    rest_setup_views,
    runtime_transition_views,
    source_preparation_views,
    source_revision_views,
    views,
)

app_name = "console"

urlpatterns = [
    path(
        "scenarios/id/<uuid:public_id>/data-refresh/",
        runtime_transition_views.review,
        name="scenario_runtime_transition",
    ),
    path(
        "scenarios/id/<uuid:public_id>/publish/",
        publication_views.publish,
        name="scenario_publish",
    ),
    path(
        "connector-sources/<int:source_pk>/edit/",
        source_revision_views.edit,
        name="connector_source_edit",
    ),
    path(
        "connector-sources/<int:source_pk>/select/",
        source_revision_views.select,
        name="connector_source_select",
    ),
    path(
        "document-sets/<uuid:public_id>/preparation/",
        preparation_settings_views.configure,
        name="document_set_preparation_settings",
    ),
    path(
        "connector-sources/<int:source_pk>/mcp-schedule/",
        mcp_schedule_views.configure,
        name="mcp_schedule_configure",
    ),
    path("rest-setup/", rest_setup_entry.start, name="rest_setup_start"),
    path(
        "document-sets/<uuid:public_id>/connectors/rest/saved/<uuid:draft_id>/resume/",
        rest_setup_views.resume,
        name="rest_setup_resume",
    ),
    path(
        "document-sets/<uuid:public_id>/connectors/rest/new/<uuid:draft_id>/probe/",
        rest_setup_views.probe,
        name="rest_setup_probe",
    ),
    path(
        "document-sets/<uuid:public_id>/connectors/rest/new/",
        rest_setup_views.setup,
        name="rest_setup_new",
    ),
    path(
        "document-sets/<uuid:public_id>/connectors/rest/new/<uuid:draft_id>/",
        rest_setup_views.setup,
        name="rest_setup_draft",
    ),
    path(
        "connector-sources/<int:source_pk>/jobs/<uuid:public_id>/action/",
        mcp_source_views.job_action,
        name="connector_job_action",
    ),
    path(
        "document-sets/<uuid:public_id>/connectors/mcp/new/",
        mcp_source_views.create_source,
        name="mcp_source_create_public",
    ),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="console/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("health/<slug:category>/", views.health_issues, name="health_issues"),
    path("switch-organization/", views.switch_organization, name="switch_organization"),
    path("o/<slug:slug>/", views.organization_detail, name="organization_detail"),
    path("organizations/", views.organizations, name="organizations"),
    path("organizations/new/", views.organization_create, name="organization_create"),
    path("projects/", views.projects, name="projects"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/id/<uuid:public_id>/", views.project_detail, name="project_detail_public"),
    path(
        "projects/id/<uuid:public_id>/access/", access_views.project_access, name="project_access"
    ),
    path("scenarios/", views.scenarios, name="scenarios"),
    path("scenarios/new/", views.scenario_create, name="scenario_create"),
    path(
        "projects/id/<uuid:project_public_id>/scenarios/new/",
        views.scenario_create,
        name="project_scenario_create",
    ),
    path("scenarios/<int:pk>/", views.scenario_detail, name="scenario_detail"),
    path("scenarios/id/<uuid:public_id>/", views.scenario_detail, name="scenario_detail_public"),
    path(
        "scenarios/id/<uuid:public_id>/data-access/",
        data_access_views.scenario_data_access,
        name="scenario_data_access",
    ),
    path(
        "document-sets/id/<uuid:public_id>/shared-access/",
        data_access_views.document_shared_access,
        name="document_shared_access",
    ),
    path(
        "scenarios/id/<uuid:public_id>/access/",
        access_views.scenario_access,
        name="scenario_access",
    ),
    path(
        "scenarios/id/<uuid:public_id>/artifacts/new/",
        views.scenario_artifact_create,
        name="scenario_artifact_create",
    ),
    path(
        "scenarios/id/<uuid:public_id>/lifecycle/",
        views.scenario_lifecycle_change,
        name="scenario_lifecycle_change",
    ),
    path(
        "scenarios/id/<uuid:public_id>/test-questions/",
        views.scenario_test_questions,
        name="scenario_test_questions",
    ),
    path(
        "scenarios/id/<uuid:public_id>/publish-and-verify/",
        views.scenario_publish_and_verify,
        name="scenario_publish_and_verify",
    ),
    path(
        "scenarios/id/<uuid:public_id>/promote/",
        views.scenario_promote,
        name="scenario_promote",
    ),
    path(
        "scenarios/id/<uuid:public_id>/ask/",
        views.scenario_ask,
        name="scenario_ask",
    ),
    path(
        "scenarios/id/<uuid:public_id>/compile-candidate/",
        views.scenario_compile_candidate,
        name="scenario_compile_candidate",
    ),
    path(
        "scenarios/id/<uuid:public_id>/artifact-options/",
        views.scenario_artifact_options,
        name="scenario_artifact_options",
    ),
    path(
        "scenarios/id/<uuid:public_id>/document-sets/bind/",
        views.scenario_bind_document_set,
        name="scenario_bind_document_set_public",
    ),
    path(
        "scenarios/id/<uuid:public_id>/document-set-bindings/<int:binding_pk>/remove/",
        views.scenario_unbind_document_set,
        name="scenario_unbind_document_set_public",
    ),
    path(
        "scenarios/id/<uuid:public_id>/document-sets/<int:document_set_pk>/grant-consumer/",
        views.scenario_grant_consumer,
        name="scenario_grant_consumer_public",
    ),
    path(
        "scenarios/id/<uuid:public_id>/document-set-grants/<int:grant_pk>/remove/",
        views.scenario_revoke_consumer,
        name="scenario_revoke_consumer_public",
    ),
    path(
        "scenarios/<int:pk>/document-sets/bind/",
        views.scenario_bind_document_set,
        name="scenario_bind_document_set",
    ),
    path(
        "scenarios/<int:pk>/document-set-bindings/<int:binding_pk>/remove/",
        views.scenario_unbind_document_set,
        name="scenario_unbind_document_set",
    ),
    path(
        "scenarios/<int:pk>/document-sets/<int:document_set_pk>/grant-consumer/",
        views.scenario_grant_consumer,
        name="scenario_grant_consumer",
    ),
    path(
        "scenarios/<int:pk>/document-set-grants/<int:grant_pk>/remove/",
        views.scenario_revoke_consumer,
        name="scenario_revoke_consumer",
    ),
    path("consumers/", views.consumers, name="consumers"),
    path("consumers/new/", views.consumer_create, name="consumer_create"),
    path("consumers/<int:pk>/", views.consumer_detail, name="consumer_detail"),
    path("consumers/id/<uuid:public_id>/", views.consumer_detail, name="consumer_detail_public"),
    path(
        "consumers/id/<uuid:public_id>/tokens/issue/",
        views.consumer_token_issue,
        name="consumer_token_issue",
    ),
    path(
        "consumers/id/<uuid:public_id>/tokens/<int:token_id>/rotate/",
        views.consumer_token_rotate,
        name="consumer_token_rotate",
    ),
    path(
        "consumers/id/<uuid:public_id>/tokens/<int:token_id>/revoke/",
        views.consumer_token_revoke,
        name="consumer_token_revoke",
    ),
    path("bindings/new/", views.binding_create, name="binding_create"),
    path("artifacts/", views.artifacts, name="artifacts"),
    path("artifacts/<int:pk>/", views.artifact_detail, name="artifact_detail"),
    path("platform/setup/", views.platform_setup, name="platform_setup"),
    path(
        "platform/setup/profiles/<slug:profile_kind>/new/",
        views.platform_profile_create,
        name="platform_profile_create",
    ),
    path(
        "platform/setup/profiles/<slug:profile_kind>/<uuid:public_id>/disable/",
        views.platform_profile_disable,
        name="platform_profile_disable",
    ),
    path(
        "platform/setup/profiles/<slug:profile_kind>/<uuid:public_id>/grant/",
        views.platform_profile_grant,
        name="platform_profile_grant",
    ),
    path("releases/", views.releases, name="releases"),
    path("releases/<int:release_id>/", views.release_detail, name="release_detail"),
    path("releases/<int:release_id>/eval/", views.release_run_eval, name="release_run_eval"),
    path("question-sets/", views.question_sets, name="question_sets"),
    path(
        "question-sets/id/<uuid:public_id>/",
        views.question_set_detail,
        name="question_set_detail",
    ),
    path(
        "question-sets/id/<uuid:public_id>/update/",
        views.question_set_update,
        name="question_set_update",
    ),
    path(
        "question-sets/id/<uuid:public_id>/publish/",
        views.question_set_publish,
        name="question_set_publish",
    ),
    path(
        "question-sets/id/<uuid:public_id>/evaluate/retrieval/",
        views.question_set_start_retrieval,
        name="question_set_start_retrieval",
    ),
    path(
        "question-sets/id/<uuid:public_id>/evaluate/answer/",
        views.question_set_start_answer,
        name="question_set_start_answer",
    ),
    path(
        "question-evaluations/id/<uuid:public_id>/",
        views.question_evaluation_detail,
        name="question_evaluation_detail",
    ),
    path(
        "question-evaluations/id/<uuid:public_id>/cancel/",
        views.question_evaluation_cancel,
        name="question_evaluation_cancel",
    ),
    path("releases/<int:release_id>/promote/", views.release_promote, name="release_promote"),
    path("releases/<int:release_id>/rollback/", views.release_rollback, name="release_rollback"),
    path("releases/<int:release_id>/canary/", views.canary_start, name="canary_start"),
    path("canaries/<int:canary_id>/stop/", views.canary_stop, name="canary_stop"),
    path("builder/", views.builder, name="builder"),
    path("documents/", views.documents, name="documents"),
    path(
        "documents/advanced/",
        views.advanced_document_inventory,
        name="advanced_document_inventory",
    ),
    path("documents/upload/", views.document_upload, name="document_upload"),
    path(
        "documents/<int:pk>/soft-delete/",
        views.document_soft_delete,
        name="document_soft_delete",
    ),
    path("documents/<int:pk>/purge/", views.document_purge, name="document_purge"),
    path(
        "documents/id/<uuid:public_id>/soft-delete/",
        views.document_soft_delete,
        name="document_soft_delete_public",
    ),
    path(
        "documents/id/<uuid:public_id>/purge/",
        views.document_purge,
        name="document_purge_public",
    ),
    path("document-sets/new/", views.document_set_create, name="document_set_create"),
    path("access/members/", views.organization_members, name="organization_members"),
    path("access/members/add/", views.organization_member_add, name="organization_member_add"),
    path(
        "access/members/<int:membership_id>/remove/",
        views.organization_member_remove,
        name="organization_member_remove",
    ),
    path(
        "access/assignments/add/",
        views.delegated_assignment_add,
        name="delegated_assignment_add",
    ),
    path(
        "access/assignments/<str:assignment_type>/<int:assignment_id>/remove/",
        views.delegated_assignment_remove,
        name="delegated_assignment_remove",
    ),
    path("document-sets/<int:pk>/", views.document_set_detail, name="document_set_detail"),
    path(
        "document-sets/id/<uuid:public_id>/",
        views.document_set_detail,
        name="document_set_detail_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/quarantine/",
        views.document_set_quarantine_change,
        name="document_set_quarantine_change",
    ),
    path(
        "document-sets/id/<uuid:public_id>/profile-artifacts/publish/",
        views.document_set_profile_artifact_publish,
        name="document_set_profile_artifact_publish",
    ),
    path(
        "document-sets/id/<uuid:public_id>/ask/",
        views.document_set_ask,
        name="document_set_ask",
    ),
    path(
        "document-sets/id/<uuid:public_id>/documents/id/<uuid:document_public_id>/",
        views.document_set_document_detail,
        name="document_set_document_detail",
    ),
    path(
        "document-sets/id/<uuid:public_id>/documents/id/<uuid:document_public_id>/versions/<int:version_id>/preview/",
        views.document_version_preview,
        name="document_version_preview",
    ),
    path(
        "document-sets/id/<uuid:public_id>/documents/id/<uuid:document_public_id>/versions/<int:version_id>/download/",
        views.document_version_download,
        name="document_version_download",
    ),
    path(
        "document-sets/id/<uuid:public_id>/documents/id/<uuid:document_public_id>/replace/",
        views.document_set_document_replace,
        name="document_set_document_replace",
    ),
    path(
        "document-sets/id/<uuid:public_id>/documents/id/<uuid:document_public_id>/tombstone/",
        views.document_set_document_tombstone,
        name="document_set_document_tombstone",
    ),
    path(
        "document-sets/id/<uuid:public_id>/connectors/",
        views.document_set_connectors,
        name="document_set_connectors_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/connectors/confluence/new/",
        views.confluence_source_create,
        name="confluence_source_create_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/connectors/rest-contract/preview/",
        views.rest_contract_preview,
        name="rest_contract_preview_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/connectors/rest-contract/new/",
        views.rest_contract_create,
        name="rest_contract_create_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/connectors/rest/new/",
        views.rest_source_create,
        name="rest_source_create_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/bulk-upload/",
        views.document_set_bulk_upload,
        name="document_set_bulk_upload_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/versions/new/",
        views.document_set_version_create,
        name="document_set_version_create_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/bind-scenario/",
        views.document_set_bind_scenario,
        name="document_set_bind_scenario_public",
    ),
    path(
        "document-sets/id/<uuid:public_id>/grant-consumer/",
        views.document_set_grant_consumer,
        name="document_set_grant_consumer_public",
    ),
    path(
        "document-sets/<int:pk>/connectors/",
        views.document_set_connectors,
        name="document_set_connectors",
    ),
    path(
        "document-sets/<int:pk>/connectors/confluence/new/",
        views.confluence_source_create,
        name="confluence_source_create",
    ),
    path(
        "document-sets/<int:pk>/connectors/rest-contract/preview/",
        views.rest_contract_preview,
        name="rest_contract_preview",
    ),
    path(
        "document-sets/<int:pk>/connectors/rest-contract/new/",
        views.rest_contract_create,
        name="rest_contract_create",
    ),
    path(
        "document-sets/<int:pk>/connectors/rest/new/",
        views.rest_source_create,
        name="rest_source_create",
    ),
    path(
        "connector-sources/<int:source_pk>/",
        views.connector_source_detail,
        name="connector_source_detail",
    ),
    path(
        "connector-sources/<int:source_pk>/run/",
        views.connector_source_run,
        name="connector_source_run",
    ),
    path(
        "connector-sources/<int:source_pk>/jobs/<uuid:job_public_id>/prepare/",
        source_preparation_views.prepare,
        name="connector_source_prepare",
    ),
    path(
        "connector-sources/<int:source_pk>/schedule/",
        views.connector_schedule_configure,
        name="connector_schedule_configure",
    ),
    path(
        "document-sets/<int:pk>/bulk-upload/",
        views.document_set_bulk_upload,
        name="document_set_bulk_upload",
    ),
    path(
        "document-sets/<int:pk>/versions/new/",
        views.document_set_version_create,
        name="document_set_version_create",
    ),
    path(
        "document-set-versions/<int:version_pk>/branch/",
        views.document_set_version_branch,
        name="document_set_version_branch",
    ),
    path(
        "document-set-versions/<int:version_pk>/add-member/",
        views.document_set_add_member,
        name="document_set_add_member",
    ),
    path(
        "document-set-versions/<int:version_pk>/members/<int:membership_pk>/remove/",
        views.document_set_remove_member,
        name="document_set_remove_member",
    ),
    path(
        "document-set-versions/<int:version_pk>/publish/",
        views.document_set_version_publish,
        name="document_set_version_publish",
    ),
    path(
        "document-set-versions/<int:version_pk>/build-index/",
        views.document_set_build_index,
        name="document_set_build_index",
    ),
    path(
        "document-set-indexes/<int:index_pk>/promote/",
        views.document_set_promote_index,
        name="document_set_promote_index",
    ),
    path(
        "document-set-index-jobs/<uuid:public_id>/cancel/",
        views.document_set_cancel_build_job,
        name="document_set_cancel_build_job",
    ),
    path(
        "document-set-index-jobs/<uuid:public_id>/retry/",
        views.document_set_retry_build_job,
        name="document_set_retry_build_job",
    ),
    path(
        "document-sets/<int:pk>/bind-scenario/",
        views.document_set_bind_scenario,
        name="document_set_bind_scenario",
    ),
    path(
        "document-set-bindings/<int:binding_pk>/remove/",
        views.document_set_unbind_scenario,
        name="document_set_unbind_scenario",
    ),
    path(
        "document-sets/<int:pk>/grant-consumer/",
        views.document_set_grant_consumer,
        name="document_set_grant_consumer",
    ),
    path(
        "document-set-grants/<int:grant_pk>/remove/",
        views.document_set_revoke_grant,
        name="document_set_revoke_grant",
    ),
    path("runs/", views.runs, name="runs"),
    path(
        "runs/runtime-control/",
        views.runtime_control_change,
        name="runtime_control_change",
    ),
    path("retention/", views.retention_operations, name="retention_operations"),
    path("workflow-runs/", views.workflow_runs, name="workflow_runs"),
    path("workflow-runs/<uuid:run_id>/", views.workflow_run_detail, name="workflow_run_detail"),
    path(
        "workflow-runs/<uuid:run_id>/cancel/",
        views.workflow_run_cancel,
        name="workflow_run_cancel",
    ),
    path(
        "workflow-runs/<uuid:run_id>/recovery/",
        views.workflow_run_recovery_decide,
        name="workflow_run_recovery_decide",
    ),
    path("tool-approvals/", views.tool_approvals, name="tool_approvals"),
    path(
        "tool-approvals/<int:approval_id>/decide/",
        views.tool_approval_decide,
        name="tool_approval_decide",
    ),
    path(
        "tool-invocations/<int:invocation_id>/cancel/",
        views.tool_invocation_cancel,
        name="tool_invocation_cancel",
    ),
    path(
        "workflow-human-tasks/<uuid:wait_id>/decide/",
        views.workflow_human_task_decide,
        name="workflow_human_task_decide",
    ),
]
