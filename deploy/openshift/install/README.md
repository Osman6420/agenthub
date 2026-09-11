# Ubuntu üzerinden OpenShift hızlı kurulum

Bu dizin, OpenShift `restricted` SCC altında AgentHub ve isteğe bağlı external-consumer demosunu
kurar. Container'lar root istemez, sabit UID kullanmaz, tüm capability'leri düşürür, read-only root
filesystem kullanır ve her container için CPU, RAM ve ephemeral-storage request/limit tanımlar.

Ayrıntılı ve otoritatif runbook:
[OpenShift installation from Ubuntu](../../../docs/operations/openshift-ubuntu-installation.md).

## Ön koşullar

- Ubuntu terminalinde `oc`, `curl`, `openssl`, `python3` ve image build aracı;
- `oc login` yapılmış, hedef namespace'te gerekli kaynakları yönetebilen kullanıcı;
- pgvector etkin PostgreSQL için ayrı migration ve kısıtlı runtime bağlantıları;
- Redis ve S3-compatible object storage;
- registry'ye push edilmiş digest-pinned application, static ve isteğe bağlı demo image'ları;
- model, embedding, storage ve demo için gerekli DNS/TLS/egress izinleri.

## Yapılandırma

```sh
cp deploy/openshift/install/openshift.env.example deploy/openshift/install/openshift.env
chmod 600 deploy/openshift/install/openshift.env
```

`openshift.env` içindeki bütün `REPLACE` alanlarını doldurun. Gemini varsayımı yoktur:

- `MODEL_HOST`, `MODEL_PORT`, `MODEL_PATH`, `MODEL_NAME`, `MODEL_API_KEY`;
- `EMBEDDING_HOST`, `EMBEDDING_PORT`, `EMBEDDING_PATH`, `EMBEDDING_NAME`,
  `EMBEDDING_DIMENSIONS`, `EMBEDDING_INDEX_TYPE`, `EMBEDDING_API_KEY`.

Adresler OpenAI-compatible HTTPS sözleşmesini desteklemelidir. `*_HOST` alanına `https://`
yazmayın; path'i ayrı verin. API key'ler yalnızca OpenShift Secret'a aktarılır. Shell açısından özel
karakter içeren değerleri tek tırnakla yazın ve bu dosyayı commit etmeyin.

## Kurulum

```sh
chmod +x deploy/openshift/install/install.sh
./deploy/openshift/install/install.sh deploy/openshift/install/openshift.env
```

Script migration ve bootstrap Job'larını tamamlamadan uygulamayı hazır saymaz; bütün Deployment
rollout'larını ve HTTPS readiness'i bekler. `INSTALL_EXTERNAL_DEMO=true` ise Wikipedia RAG demosunu
generic model/embedding profilleriyle seed eder ve ayrı TLS Route açar.

## Kontrol

```sh
oc get pods,jobs,routes -n "$NAMESPACE"
curl --fail "https://$ROUTE_HOST/v1/health/ready"
oc exec -n "$NAMESPACE" deployment/agenthub-web -- id
```

Pod UID'si sıfır olmamalıdır. Sorunu `anyuid`, root, privileged SCC, limitsiz container veya writable
root filesystem vererek çözmeyin. Cluster'a özel egress policy, private registry pull Secret, custom
CA, quota ve managed-service bağlantı kararları için tam runbook'taki review kapılarını uygulayın.
