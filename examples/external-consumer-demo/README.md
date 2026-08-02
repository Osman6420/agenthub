# External Consumer Demo

This is a standalone loopback client, not an AgentHub application route. It serves static HTML on
`127.0.0.1:4173` and proxies only the allowlisted public consumer API paths to `127.0.0.1:8000`.
Bearer tokens stay server-side in the gitignored `credentials.local.json`.

## Bootstrap

Run inside the current Compose web service after the Gemini runtime environment is configured:

```powershell
docker compose -f deploy/compose/docker-compose.yml exec -T web python manage.py seed_external_consumer_demo `
  --credentials-file /app/examples/external-consumer-demo/credentials.local.json
```

The command prints the local operator login and three one-time consumer tokens. It downloads the
current plaintext extract for the Turkish Wikipedia `İstanbul` page through a fixed, bounded HTTPS
request, creates a managed document-set index, and serves four scenarios.

## Serve

```powershell
.venv\Scripts\python.exe examples\external-consumer-demo\server.py
```

Open `http://127.0.0.1:4173`. The server binds only to loopback and does not expose the operator
password or consumer tokens to browser JavaScript.
