# Önerilen model sınırları ve mevcut 80 modelin karşılığı

2026-09-08 tasarım adayı. Uygulanmış şema veya onaylanmış migration değildir. Kullanıcının ekip izolasyonu, uzun ajan, insan onayı, paralellik ve telafi gereksinimlerini kapsar. [Ana değerlendirme](assessment.md).

## Sayımın anlamı

Aşağıdaki referans tasarım **35 uygulama modeli/tablosu** içerir. Bu sabit bir bütçe değildir; ilişki, indeks, saklama ve performans doğrulaması sonrası değişebilir. Django kullanıcı/oturum/izin/migration tabloları ve vektör partition/store tabloları ayrıca sayılmalıdır. 35 sayısı toplam fiziksel tablo garantisi değildir. İstemci ve çözüm ilişki tabloları bu sayıya dahildir; gizli M2M tabloları varsayılmadı.

| Alan | Adet | Açık model listesi |
|---|---:|---|
| Ekip ve üyelik | 2 | `Workspace`, `WorkspaceMembership` |
| Çözüm ve tek yayın sürümü | 4 | `Solution`, `SolutionRevision`, `SolutionCollection`, `SolutionTool` |
| API erişimi | 3 | `ApiClient`, `ApiCredential`, `ClientSolutionGrant` |
| Bağlantılar | 1 | `Connection` |
| Bilgi tabanı | 7 | `Collection`, `Source`, `Document`, `DocumentRevision`, `IndexGeneration`, `IndexGenerationDocument`, `Chunk` |
| Arka plan işleri | 2 | `Job`, `Outbox` |
| Araç ve onay | 3 | `Tool`, `ToolInvocation`, `ApprovalRequest` |
| Kalıcı yürütme | 8 | `Run`, `RunWait`, `RunBranch`, `RunJoin`, `RunChildLink`, `RunCompensationEntry`, `RunEvent`, `RuntimeControl` |
| Kalite değerlendirme | 3 | `TestCase`, `EvalRun`, `EvalResult` |
| Denetim ve tüketim | 2 | `AuditEvent`, `UsageRecord` |

## Mevcut modellerin tasarım karşılığı

Her satır mevcut bir somut uygulama modelidir. Birleştirme, davranış değişikliği veya kapsam dışına alma ifade eder; doğrudan tablo silme talimatı değildir. Özellikle yetki modeli değişimi mevcut davranışla birebir uyumlu olmayacaktır.

| Mevcut model | Önerilen karşılık / açık kapsam kararı |
|---|---|
| `Organization` | Workspace |
| `OrganizationMembership` | WorkspaceMembership |
| `PlatformResponsibilityAssignment` | Django platform role; workspace data access ayrı |
| `OrganizationResponsibilityAssignment` | WorkspaceMembership |
| `ProjectResponsibilityAssignment` | WorkspaceMembership; proje yetki sınırı kalkar |
| `ScenarioResponsibilityAssignment` | WorkspaceMembership |
| `DocumentSetResponsibilityAssignment` | WorkspaceMembership |
| `Consumer` | ApiClient |
| `ConsumerToken` | ApiCredential |
| `ConsumerBinding` | ClientSolutionGrant |
| `AIProject` | Solution üzerindeki düzenleme etiketi; ayrı yetki/lifecycle yok |
| `Scenario` | Solution |
| `ScenarioAlias` | Solution stable slug; alias redirect isteğe bağlı |
| `ArtifactVersion` | SolutionRevision; bağlantı/araç tanımı Connection/Tool ve snapshot |
| `ScenarioRelease` | SolutionRevision |
| `ReleaseCanary` | İlk hedefte yok; kontrollü trafik bölme isteğe bağlı |
| `RestPullProfile` | Connection |
| `RestPullContract` | Source.config, Job giriş snapshot |
| `ConfluenceProfile` | Connection |
| `Source` | Source |
| `IndexVersion` | IndexGeneration |
| `DocumentSetPreparationProfile` | Collection.settings |
| `IngestionRun` | Job |
| `TenantConfluenceProfileGrant` | Connection.workspace; ekipler arası paylaşım yok |
| `TenantRestPullProfileGrant` | Connection.workspace; ekipler arası paylaşım yok |
| `RestSyncRun` | Job |
| `RestDocumentCursor` | Document external_id/revision/cursor alanları |
| `ConnectorSyncSchedule` | Source schedule alanları |
| `ConnectorSchedulePromotionTarget` | Collection otomatik güncelleme politikası |
| `ConfluenceSyncRun` | Job |
| `ConfluenceDocumentCursor` | Document external_id/revision/cursor alanları |
| `IndexedDocument` | DocumentRevision |
| `Chunk` | Chunk |
| `EmbeddingProfile` | Connection + IndexGeneration embedding_spec |
| `TenantEmbeddingProfileGrant` | Connection.workspace; ortak platform bağlantı grant'i opsiyonel |
| `OcrProfile` | Connection |
| `TenantOcrProfileGrant` | Connection.workspace |
| `DocumentOcrJob` | Job; kalıcı OCR sonucu ve ACK bilgisi korunur |
| `StagedIndexBuildJob` | Job + IndexGeneration |
| `StagedIndexBuildOutbox` | Outbox |
| `IngestionWorkerHeartbeat` | Operasyonel TTL heartbeat; worker-contract kontrolü Job/Run'da |
| `Document` | Document |
| `DocumentVersion` | DocumentRevision |
| `DocumentVersionSummary` | İlk hedefte ayrı hiyerarşik özet kataloğu yok; opsiyonel |
| `DocumentSet` | Collection |
| `DocumentSetVersion` | IndexGeneration teknik snapshot; manuel set yayını kalkar |
| `DocumentSetMembership` | IndexGenerationDocument |
| `ScenarioDocumentSetBinding` | SolutionCollection |
| `ScenarioDocumentSetAccessRequest` | İlk hedefte yok; ekip içi rol yeterli |
| `ScenarioDocumentSetGrant` | WorkspaceMembership + SolutionCollection |
| `DocumentSetGrant` | ClientSolutionGrant + yayınlanmış SolutionCollection kapsamı |
| `ModelProfile` | Connection + SolutionRevision resolved model spec |
| `CustomNodeDefinition` | İlk hedefte paket yükleme/katalog yok; kodla dağıtılan allowlist |
| `WorkflowVersion` | SolutionRevision.compiled_graph + engine_contract_version |
| `Run` | Run |
| `RunWait` | RunWait |
| `RunChildLink` | RunChildLink |
| `RunCompensationEntry` | RunCompensationEntry |
| `RunBranch` | RunBranch |
| `RunJoin` | RunJoin |
| `RunEvent` | RunEvent |
| `McpCatalogSource` | Connection |
| `McpCatalogCandidate` | Tool draft/status; otomatik aktifleştirme yok |
| `ToolDefinition` | Tool |
| `ToolBinding` | SolutionTool içindeki immutable snapshot |
| `ToolInvocation` | ToolInvocation |
| `ApprovalRequest` | ApprovalRequest |
| `AgentRuntimeControl` | RuntimeControl; platform/workspace/solution kapsamları |
| `WorkflowDraft` | Solution.draft_config |
| `ArtifactDraft` | Solution.draft_config / Tool / Connection editörleri |
| `EvalRun` | EvalRun purpose=release_gate |
| `EvalCaseResult` | EvalResult |
| `QuestionSet` | TestCase grouping; bağımsız soru seti kataloğu opsiyonel |
| `QuestionSetVersion` | EvalRun case_snapshot; soru seti sürümü opsiyonel |
| `QuestionCase` | TestCase |
| `QuestionEvaluationRun` | EvalRun purpose=benchmark/diagnostic |
| `QuestionEvaluationEvidence` | EvalResult; hassas alanlar ayrı yetki/retention |
| `UsageEvent` | UsageRecord |
| `AuditEvent` | AuditEvent |
| `IdempotencyRecord` | Run admission: ClientSolutionGrant scope + idempotency unique; conflict checksum korunur |

## İlave modül gerektirebilecek kapsam

Kaynak sistemden kullanıcı bazlı ACL devralma, ekipler arası veri/bağlantı paylaşımı, bağımsız reusable prompt/soru-seti kataloğu, canary yönlendirme, arbitrary Python paket yönetimi, kalıcı konuşmalar veya karmaşık MCP OAuth token depolama gerekirse ek modeller beklenir. Bunların tümünü JSON alanlarında saklayarak 35 sayısını korumaya çalışmak önerilmez.

Ekipler içinde de doküman bazlı gizlilik gerekiyorsa yalnız WorkspaceMembership yeterli değildir: bu tasarım ya daha küçük çalışma alanlarına ayrılmalı ya da açık ACL modelleri eklenmelidir. Bu tercih gizli bir varsayım olarak uygulanmamalıdır.

## Önemli alan ve bütünlük sözleşmeleri

| Sınır | Hedef sözleşme |
|---|---|
| WorkspaceMembership | `(workspace_id, user_id)` tekil; aktiflik, sınırlı rol/approval yetkisi; DB politikası ve servisler aynı workspace'i kullanır. |
| Solution | `workspace_id`, sabit dış kimlik/slug, küçük `draft_config`, düzenleme revision'ı, `active_revision_id`, enabled; aktif revision aynı solution/workspace'e ait olmalı. |
| SolutionRevision | `(solution_id, number)` tekil; immutable config/compiled graph/checksum/engine contract; publish yapan kişi ve zaman. Taslak snapshot'ı da çalışmaya başlarken sabitlenir. |
| SolutionCollection / SolutionTool | Mutable Solution'a genel global grant yerine exact SolutionRevision'a bağlı ilişkiler. Tool snapshot'ı ve override sınırları burada; aynı workspace kontrolü. Draft JSON referansı runtime yetkisi değildir. |
| ClientSolutionGrant | `(client_id, solution_id)` tekil; capability/action allowlist; client ve solution workspace eşleşmesi. Çözüm çalıştırma izni key sahibine genel koleksiyon browse izni vermez. |
| Connection | Workspace sahibi, type, durum ve tip doğrulamalı config/secret referansı. Endpoint/TLS/private-network kuralı ayrı güvenli adapter/policy katmanında. Aynı tür olmayan bağlantılar yanlış role bağlanamaz. Secret plaintext snapshot'a girmez. |
| Source / Document | Source tek Collection'a ait; takvim ve son başarılı kaynak checkpoint'i taşır. Document için `(source_id, external_id)` tekil; yerel upload için sistem external ID; checksum, görülme ve tombstone bilgisi. |
| DocumentRevision | `(document_id, revision)` tekil; içerik checksum'ı ve blob/parse sonucu referansı; büyük içerik JSON'a gömülmez. Aynı içerik kullanılabilirken referansı yerinde değiştirilemez. |
| IndexGeneration / membership | Aynı collection'a ait immutable hazırlama spec'i, model/embedding space, durum; Collection.active_generation_id atomik değişir. Membership `(generation_id, document_id)` tekil ve exact DocumentRevision'a bağlı; cross-workspace bağ reddedilir. Manifest tamlığı kanıtlanmadan aktive edilmez. |
| Chunk | DocumentRevision + embedding/chunking spec kimliği + ordinal/kind tekilliği; farklı model vektörleri karşılaştırılmaz. Retrieval workspace, generation üyeliği ve canlı tombstone/ACL kesişimini uygular. |
| Job / Outbox | Dar kapsam: source sync, parse/OCR ve index preparation. Kind'e göre kapalı giriş/sonuç şeması, exact target, idempotency, retry, claim/fencing ve external job/ACK bilgisi. İş niyeti ve outbox atomik; enqueue kaybı geri kazanılabilir. Genel workflow Run ile birleştirilmez. |
| Run / child durumları | Exact SolutionRevision, actor/client/workspace, engine contract, request checksum, lease/checkpoint; wait/parallel/child/compensation tekillik ve yetki kuralları eşdeğer biçimde korunur. Runtime verisi yalnız log değildir. |
| ToolInvocation / ApprovalRequest | İşlem girdisi, hedef snapshot'ı, idempotency, gerçek initiator, approver, expiry ve sonuç; belirsiz yan etki otomatik yeniden denenmez. Onaylanan girdi değiştirilirse onay geçersizdir. |
| EvalRun / EvalResult | `purpose` ayrımı, exact solution/generation ve case snapshot, sonuç formatı, content erişimi/retention; diagnostic sonucu release gate kanıtı sayılamaz. |
| Audit / Usage | Audit aktör, işlem, hedef, karar ve sonucu taşır; yüksek hacimli token/tüketim kayıtları farklı tutulur. İçerik ve secret telemetry'ye kopyalanmaz. |

Bunlar tasarım invariants'ıdır; yalnız Django `clean()` çağrılarına güvenmek yeterli sayılmamalı. Uygun unique/check/FK kısıtları, transaction sınırları, RLS ve servis doğrulaması birlikte tasarlanmalı. Snapshot JSON'u için sürümlü kapalı şema ve boyut sınırı gerekir; bağımsız yetki kaynağı haline getirilmemeli.
