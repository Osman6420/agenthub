# Sabit tablo envanteri

2026-09-08 çalışma ağacından Django model metaverisiyle üretildi. 80 uygulama + 9 Django model/ara tablosu; ayrıca `django_migrations` ile 90 sabit tablo. Yerel PostgreSQL’de bunlara ek 9 `chunk_iv_*` tablosu mevcut. Satır sayıları bu dosyada yer almaz.

## admin (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `django_admin_log` | `LogEntry` | user → auth_user; content_type → django_content_type |

## auth (6)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `auth_permission` | `Permission` | content_type → django_content_type |
| `auth_group_permissions` | `Group_permissions` | group → auth_group; permission → auth_permission |
| `auth_group` | `Group` | — |
| `auth_user_groups` | `User_groups` | user → auth_user; group → auth_group |
| `auth_user_user_permissions` | `User_user_permissions` | user → auth_user; permission → auth_permission |
| `auth_user` | `User` | — |

## contenttypes (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `django_content_type` | `ContentType` | — |

## sessions (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `django_session` | `Session` | — |

## tenancy (2)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `tenancy_organization` | `Organization` | — |
| `tenancy_organizationmembership` | `OrganizationMembership` | organization → tenancy_organization; user → auth_user; created_by → auth_user; revoked_by → auth_user |

## identity (8)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `identity_platformresponsibilityassignment` | `PlatformResponsibilityAssignment` | user → auth_user; assigned_by → auth_user; revoked_by → auth_user |
| `identity_organizationresponsibilityassignment` | `OrganizationResponsibilityAssignment` | organization → tenancy_organization; membership → tenancy_organizationmembership; assigned_by → auth_user; revoked_by → auth_user |
| `identity_projectresponsibilityassignment` | `ProjectResponsibilityAssignment` | organization → tenancy_organization; membership → tenancy_organizationmembership; assigned_by → auth_user; revoked_by → auth_user; project → catalog_aiproject |
| `identity_scenarioresponsibilityassignment` | `ScenarioResponsibilityAssignment` | organization → tenancy_organization; membership → tenancy_organizationmembership; assigned_by → auth_user; revoked_by → auth_user; scenario → catalog_scenario |
| `identity_documentsetresponsibilityassignment` | `DocumentSetResponsibilityAssignment` | organization → tenancy_organization; membership → tenancy_organizationmembership; assigned_by → auth_user; revoked_by → auth_user; document_set → documents_documentset |
| `identity_consumer` | `Consumer` | organization → tenancy_organization |
| `identity_consumertoken` | `ConsumerToken` | organization → tenancy_organization; consumer → identity_consumer |
| `identity_consumerbinding` | `ConsumerBinding` | organization → tenancy_organization; consumer → identity_consumer; scenario → catalog_scenario |

## catalog (3)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `catalog_aiproject` | `AIProject` | organization → tenancy_organization |
| `catalog_scenario` | `Scenario` | organization → tenancy_organization; project → catalog_aiproject |
| `catalog_scenarioalias` | `ScenarioAlias` | organization → tenancy_organization; scenario → catalog_scenario; redirect_to → catalog_scenario |

## artifacts (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `artifacts_artifactversion` | `ArtifactVersion` | organization → tenancy_organization |

## releases (2)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `releases_scenariorelease` | `ScenarioRelease` | organization → tenancy_organization; scenario → catalog_scenario |
| `releases_releasecanary` | `ReleaseCanary` | organization → tenancy_organization; scenario → catalog_scenario; consumer → identity_consumer; release → releases_scenariorelease |

## ingestion (25)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `ingestion_restpullprofile` | `RestPullProfile` | — |
| `ingestion_restpullcontract` | `RestPullContract` | organization → tenancy_organization |
| `ingestion_confluenceprofile` | `ConfluenceProfile` | — |
| `ingestion_source` | `Source` | organization → tenancy_organization; confluence_profile → ingestion_confluenceprofile; rest_profile → ingestion_restpullprofile; rest_contract → ingestion_restpullcontract; document_set → documents_documentset |
| `ingestion_indexversion` | `IndexVersion` | organization → tenancy_organization; source → ingestion_source; document_set_version → documents_documentsetversion; embedding_profile → ingestion_embeddingprofile; chunking_profile → artifacts_artifactversion; retrieval_profile → artifacts_artifactversion; summary_model_profile → artifacts_artifactversion; summary_prompt_contract → artifacts_artifactversion; parent_index_version → ingestion_indexversion |
| `ingestion_documentsetpreparationprofile` | `DocumentSetPreparationProfile` | organization → tenancy_organization; document_set → documents_documentset; embedding_profile → ingestion_embeddingprofile; chunking_profile → artifacts_artifactversion; retrieval_profile → artifacts_artifactversion; ocr_profile → ingestion_ocrprofile; summary_model_profile → artifacts_artifactversion; summary_prompt_contract → artifacts_artifactversion |
| `ingestion_ingestionrun` | `IngestionRun` | organization → tenancy_organization; source → ingestion_source; index_version → ingestion_indexversion |
| `ingestion_tenantconfluenceprofilegrant` | `TenantConfluenceProfileGrant` | organization → tenancy_organization; document_set → documents_documentset; confluence_profile → ingestion_confluenceprofile |
| `ingestion_tenantrestpullprofilegrant` | `TenantRestPullProfileGrant` | organization → tenancy_organization; document_set → documents_documentset; rest_profile → ingestion_restpullprofile |
| `ingestion_restsyncrun` | `RestSyncRun` | organization → tenancy_organization; source → ingestion_source; rest_profile → ingestion_restpullprofile; rest_contract → ingestion_restpullcontract; candidate_set_version → documents_documentsetversion; schedule → ingestion_connectorsyncschedule |
| `ingestion_restdocumentcursor` | `RestDocumentCursor` | organization → tenancy_organization; source → ingestion_source; document → documents_document; document_version → documents_documentversion; last_seen_run → ingestion_restsyncrun |
| `ingestion_connectorsyncschedule` | `ConnectorSyncSchedule` | organization → tenancy_organization; source → ingestion_source; embedding_profile → ingestion_embeddingprofile; ocr_profile → ingestion_ocrprofile; last_automation_candidate → documents_documentsetversion |
| `ingestion_connectorschedulepromotiontarget` | `ConnectorSchedulePromotionTarget` | organization → tenancy_organization; schedule → ingestion_connectorsyncschedule; scenario → catalog_scenario |
| `ingestion_confluencesyncrun` | `ConfluenceSyncRun` | organization → tenancy_organization; source → ingestion_source; confluence_profile → ingestion_confluenceprofile; candidate_set_version → documents_documentsetversion; schedule → ingestion_connectorsyncschedule |
| `ingestion_confluencedocumentcursor` | `ConfluenceDocumentCursor` | organization → tenancy_organization; source → ingestion_source; document → documents_document; document_version → documents_documentversion; last_seen_run → ingestion_confluencesyncrun |
| `ingestion_indexeddocument` | `IndexedDocument` | organization → tenancy_organization; index_version → ingestion_indexversion |
| `ingestion_chunk` | `Chunk` | organization → tenancy_organization; index_version → ingestion_indexversion; document → ingestion_indexeddocument |
| `ingestion_embeddingprofile` | `EmbeddingProfile` | — |
| `ingestion_tenantembeddingprofilegrant` | `TenantEmbeddingProfileGrant` | organization → tenancy_organization; embedding_profile → ingestion_embeddingprofile |
| `ingestion_ocrprofile` | `OcrProfile` | — |
| `ingestion_tenantocrprofilegrant` | `TenantOcrProfileGrant` | organization → tenancy_organization; ocr_profile → ingestion_ocrprofile |
| `ingestion_documentocrjob` | `DocumentOcrJob` | organization → tenancy_organization; document_version → documents_documentversion; ocr_profile → ingestion_ocrprofile |
| `ingestion_stagedindexbuildjob` | `StagedIndexBuildJob` | organization → tenancy_organization; document_set_version → documents_documentsetversion; embedding_profile → ingestion_embeddingprofile; ocr_profile → ingestion_ocrprofile; chunking_profile → artifacts_artifactversion; retrieval_profile → artifacts_artifactversion; summary_model_profile → artifacts_artifactversion; summary_prompt_contract → artifacts_artifactversion; result_index_version → ingestion_indexversion |
| `ingestion_stagedindexbuildoutbox` | `StagedIndexBuildOutbox` | organization → tenancy_organization; job → ingestion_stagedindexbuildjob |
| `ingestion_ingestionworkerheartbeat` | `IngestionWorkerHeartbeat` | — |

## documents (10)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `documents_document` | `Document` | organization → tenancy_organization; source → ingestion_source |
| `documents_documentversion` | `DocumentVersion` | organization → tenancy_organization; document → documents_document |
| `documents_documentversionsummary` | `DocumentVersionSummary` | organization → tenancy_organization; document_version → documents_documentversion; model_profile → artifacts_artifactversion; prompt_contract → artifacts_artifactversion |
| `documents_documentset` | `DocumentSet` | organization → tenancy_organization |
| `documents_documentsetversion` | `DocumentSetVersion` | organization → tenancy_organization; document_set → documents_documentset; built_index_version → ingestion_indexversion |
| `documents_documentsetmembership` | `DocumentSetMembership` | organization → tenancy_organization; document_set_version → documents_documentsetversion; document_version → documents_documentversion |
| `documents_scenariodocumentsetbinding` | `ScenarioDocumentSetBinding` | organization → tenancy_organization; scenario → catalog_scenario; document_set → documents_documentset |
| `documents_scenariodocumentsetaccessrequest` | `ScenarioDocumentSetAccessRequest` | organization → tenancy_organization; scenario → catalog_scenario; document_set → documents_documentset; requested_by → auth_user; decided_by → auth_user |
| `documents_scenariodocumentsetgrant` | `ScenarioDocumentSetGrant` | organization → tenancy_organization; scenario → catalog_scenario; document_set → documents_documentset; granted_by → auth_user; revoked_by → auth_user |
| `documents_documentsetgrant` | `DocumentSetGrant` | organization → tenancy_organization; document_set → documents_documentset |

## orchestration (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `orchestration_modelprofile` | `ModelProfile` | — |

## workflows (9)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `workflows_customnodedefinition` | `CustomNodeDefinition` | organization → tenancy_organization |
| `workflows_workflowversion` | `WorkflowVersion` | organization → tenancy_organization; scenario → catalog_scenario; source_artifact → artifacts_artifactversion |
| `workflows_run` | `Run` | organization → tenancy_organization; scenario → catalog_scenario; release → releases_scenariorelease; workflow_version → workflows_workflowversion; consumer → identity_consumer |
| `workflows_runwait` | `RunWait` | organization → tenancy_organization; run → workflows_run |
| `workflows_runchildlink` | `RunChildLink` | organization → tenancy_organization; parent_run → workflows_run; child_run → workflows_run |
| `workflows_runcompensationentry` | `RunCompensationEntry` | organization → tenancy_organization; run → workflows_run |
| `workflows_runbranch` | `RunBranch` | organization → tenancy_organization; run → workflows_run |
| `workflows_runjoin` | `RunJoin` | organization → tenancy_organization; run → workflows_run |
| `workflows_runevent` | `RunEvent` | organization → tenancy_organization; run → workflows_run |

## tools (6)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `tools_mcpcatalogsource` | `McpCatalogSource` | organization → tenancy_organization |
| `tools_mcpcatalogcandidate` | `McpCatalogCandidate` | organization → tenancy_organization; source → tools_mcpcatalogsource; registered_definition → tools_tooldefinition |
| `tools_tooldefinition` | `ToolDefinition` | organization → tenancy_organization |
| `tools_toolbinding` | `ToolBinding` | organization → tenancy_organization; tool_definition → tools_tooldefinition |
| `tools_toolinvocation` | `ToolInvocation` | organization → tenancy_organization; scenario → catalog_scenario; release → releases_scenariorelease; consumer → identity_consumer |
| `tools_approvalrequest` | `ApprovalRequest` | organization → tenancy_organization; invocation → tools_toolinvocation; initiated_by_user → auth_user; decided_by_user → auth_user |

## agents (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `agents_agentruntimecontrol` | `AgentRuntimeControl` | organization → tenancy_organization; project → catalog_aiproject; scenario → catalog_scenario |

## builder (2)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `builder_workflowdraft` | `WorkflowDraft` | organization → tenancy_organization; project → catalog_aiproject; scenario → catalog_scenario |
| `builder_artifactdraft` | `ArtifactDraft` | organization → tenancy_organization; project → catalog_aiproject; scenario → catalog_scenario |

## evaluations (7)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `evaluations_evalrun` | `EvalRun` | organization → tenancy_organization; release → releases_scenariorelease |
| `evaluations_evalcaseresult` | `EvalCaseResult` | organization → tenancy_organization; run → evaluations_evalrun |
| `evaluations_questionset` | `QuestionSet` | organization → tenancy_organization; scenario → catalog_scenario |
| `evaluations_questionsetversion` | `QuestionSetVersion` | organization → tenancy_organization; question_set → evaluations_questionset |
| `evaluations_questioncase` | `QuestionCase` | organization → tenancy_organization; question_set_version → evaluations_questionsetversion |
| `evaluations_questionevaluationrun` | `QuestionEvaluationRun` | organization → tenancy_organization; question_set_version → evaluations_questionsetversion; document_set_version → documents_documentsetversion; index_version → ingestion_indexversion; retrieval_profile → artifacts_artifactversion; release → releases_scenariorelease; judge_model_profile → artifacts_artifactversion; judge_prompt_contract → artifacts_artifactversion |
| `evaluations_questionevaluationevidence` | `QuestionEvaluationEvidence` | organization → tenancy_organization; run → evaluations_questionevaluationrun; question_case → evaluations_questioncase |

## observability (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `observability_usageevent` | `UsageEvent` | — |

## audit (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `audit_auditevent` | `AuditEvent` | — |

## gateway (1)

| Tablo | Model | Doğrudan ilişkiler |
|---|---|---|
| `gateway_idempotencyrecord` | `IdempotencyRecord` | organization → tenancy_organization; consumer → identity_consumer |
