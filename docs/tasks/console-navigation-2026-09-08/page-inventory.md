> Superseded: [tek aktif geliştirme görevi](../Agent_Hub_MD/plan.md). Bu belge tarihsel kaynaktır; bağımsız uygulanmaz.

# Console page inventory

Source inventory of all console templates. Browser coverage is recorded separately in verification.md.

| Template | Kind | Named destinations |
| --- | --- | --- |
| artifact_detail.html | Page | builder, release_detail, scenario_detail_public, scenarios |
| artifacts.html | Page template; no direct render in views.py | artifact_detail, organization_detail |
| base.html | Shared shell | consumers, dashboard, documents, logout, organization_members, platform_setup, projects, question_sets, runs, scenarios, switch_organization, tool_approvals |
| builder.html | Page | scenario_detail_public, scenarios |
| connector_source_detail.html | Page | connector_source_run, document_set_connectors_public, document_set_detail_public, documents |
| consumer_detail.html | Page | consumer_token_issue, consumer_token_revoke, consumer_token_rotate, consumers, document_set_detail_public, organization_detail, scenario_detail_public |
| consumer_token_reveal.html | Page | consumer_detail_public, organization_detail |
| dashboard.html | Page | health_issues, organization_create, organization_detail, organizations, runs, tool_approvals, workflow_runs |
| document_content_error.html | Page | documents |
| document_inventory_advanced.html | Page | document_purge_public, document_soft_delete_public, documents |
| document_profile_inspector.html | Partial |  |
| document_set_connectors.html | Page | confluence_source_create_public, connector_schedule_configure, connector_source_detail, connector_source_run, document_set_detail_public, documents, platform_setup, rest_contract_create_public, rest_contract_preview_public, rest_source_create_public |
| document_set_detail.html | Page | connector_source_detail, consumer_detail_public, document_set_add_member, document_set_ask, document_set_bind_scenario_public, document_set_build_index, document_set_bulk_upload_public, document_set_cancel_build_job, document_set_connectors_public, document_set_document_detail, document_set_grant_consumer_public, document_set_promote_index, document_set_quarantine_change, document_set_remove_member, document_set_retry_build_job, document_set_revoke_grant, document_set_unbind_scenario, document_set_version_branch, document_set_version_create_public, document_set_version_publish, documents, organization_detail, organization_members, question_sets, scenario_detail_public |
| document_set_document_detail.html | Page | document_set_detail_public, document_set_document_replace, document_set_document_tombstone, document_version_download, document_version_preview, documents |
| document_version_preview.html | Page | document_set_document_detail |
| documents.html | Page | document_set_create |
| error_guidance.html | Page template; no direct render in views.py | dashboard |
| field_info.html | Partial |  |
| form.html | Page |  |
| list.html | Page |  |
| login.html | Page |  |
| one_off_question_result.html | Page |  |
| organization_detail.html | Page template; no direct render in views.py | artifact_detail, consumer_detail_public, dashboard, document_set_detail_public, project_detail_public, release_detail, scenario_detail_public, workflow_run_detail |
| organization_members.html | Page | dashboard, delegated_assignment_add, delegated_assignment_remove, organization_member_add, organization_member_remove |
| platform_profile_form.html | Page | platform_setup |
| platform_profile_grant.html | Page | platform_setup |
| platform_setup.html | Page | platform_profile_create, platform_profile_disable, platform_profile_grant, retention_operations |
| profile_field_form.html | Partial |  |
| project_detail.html | Page | organization_members, project_scenario_create, projects, scenario_detail_public, scenarios (project filter) |
| question_evaluation_detail.html | Page | question_evaluation_cancel, question_evaluation_detail, question_set_detail, question_sets, release_detail, scenario_detail_public, scenario_test_questions |
| question_set_detail.html | Page | question_evaluation_detail, question_set_publish, question_set_start_answer, question_set_start_retrieval, question_set_update, question_sets |
| question_sets.html | Page | dashboard, question_evaluation_detail, question_set_detail |
| release_detail.html | Page | artifact_detail, canary_start, canary_stop, consumer_detail_public, release_promote, release_rollback, release_run_eval, releases, scenario_artifact_create, scenario_detail_public, scenarios |
| releases.html | Page | release_detail, scenario_detail_public, scenarios |
| retention_operations.html | Page | retention_operations |
| runs.html | Page | runs, runtime_control_change, scenario_detail_public, workflow_runs |
| scenario_artifact_form.html | Page | scenario_detail_public |
| scenario_create.html | Page | organization_detail, project_detail_public |
| scenario_detail.html | Page | artifact_detail, builder, consumer_detail_public, consumers, document_set_detail_public, documents, organization_members, project_detail_public, question_sets, release_detail, runtime_control_change, scenario_artifact_create, scenario_ask, scenario_bind_document_set_public, scenario_detail_public, scenario_grant_consumer_public, scenario_lifecycle_change, scenario_publish_and_verify, scenario_revoke_consumer_public, scenario_unbind_document_set_public, scenarios |
| scenario_test_questions.html | Page | project_detail_public, question_evaluation_detail, release_detail, scenario_detail_public |
| scenarios.html | Page | project_detail_public, project_scenario_create, projects, scenario_detail_public, scenarios |
| tool_approvals.html | Page | tool_approval_decide, tool_invocation_cancel |
| workflow_run_detail.html | Page | runs, workflow_run_cancel, workflow_run_recovery_decide, workflow_runs |
| workflow_runs.html | Page | workflow_runs |
