# DOS68K Slack Bot

Slack bot che espone il chatbot **DOS68K** di PagoPA agli utenti interni,
gestendo sessioni per-utente tramite Amazon DynamoDB.

---

## Architettura

```
Utente Slack
     │  messaggio
     ▼
Slack Events API
     │  POST /slack/events  (HTTPS)
     ▼
Application Load Balancer (AWS)
     │
     ▼
ECS Fargate – dos68k-slack-bot (FastAPI + Uvicorn)
     │                │
     │                └──► DynamoDB  (slack_user_id → session_id)
     │
     └──► DOS68K Chatbot API (API Gateway + ECS esistente)
               POST /sessions
               POST /queries/{sessionId}
               DELETE /sessions/{sessionId}
```

**Perché ECS Fargate e non Lambda?**

Il chatbot con RAG può impiegare > 3 secondi; Slack richiede ACK in < 3s.
Con ECS possiamo rispondere immediatamente con `200 OK` e inviare la risposta
al canale in modo asincrono (uvicorn è non-bloccante). In alternativa si può
usare Lambda + SQS per il disaccoppiamento.

---

## Componenti AWS

| Componente | Scopo |
|---|---|
| **ECS Fargate** | Hosting del bot (scalabile, no server management) |
| **ECR** | Registry immagini Docker |
| **Application Load Balancer** | Terminazione TLS + routing verso ECS |
| **DynamoDB** | Mapping sessioni Slack → DOS68K (TTL nativo) |
| **Secrets Manager** | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `CHATBOT_API_KEY` |
| **CloudWatch Logs** | Log centralizzati; health check esclusi di default |
| **IAM (OIDC)** | GitHub Actions autentica su AWS senza credenziali statiche |

---

## Variabili d'ambiente

| Variabile | Default | Descrizione |
|---|---|---|
| `SLACK_BOT_TOKEN` | – | Token OAuth Slack (da Secrets Manager) |
| `SLACK_SIGNING_SECRET` | – | Signing secret Slack (da Secrets Manager) |
| `CHATBOT_API_KEY` | – | API key DOS68K (da Secrets Manager) |
| `CHATBOT_BASE_URL` | URL DEV | Base URL chatbot |
| `DYNAMODB_SESSIONS_TABLE` | `dos68k-slack-sessions` | Nome tabella DynamoDB **(configurabile)** |
| `SLACK_SESSION_TTL_SECONDS` | `3600` | TTL sessioni Slack in secondi |
| `LOG_HEALTH_CHECKS` | `false` | Se `true`, logga le chiamate a `/health` |
| `LOG_LEVEL` | `INFO` | Livello di logging |
| `AWS_REGION` | `eu-south-1` | Regione AWS |

---

## Punti aperti risolti

### #1 – GitHub Action build + push con tag = commit SHA
Vedi `.github/workflows/deploy.yml`. Il tag dell'immagine ECR è sempre
`${{ github.sha }}` (commit SHA completo). Il job `build-and-push`
viene eseguito solo dopo il successo del job `test`.

### #2 – Unit test prima della build
Il job `deploy` ha `needs: test`. Se anche un solo test fallisce,
la build Docker non parte.

### #3 – `expiresAt` null in DynamoDB
`session_manager.compute_expires_at_epoch()` calcola `createdAt + 90 giorni`
in formato Unix epoch. Il valore viene loggato ad ogni creazione sessione.
Quando il backend DOS68K esporrà il campo in scrittura, basterà passarlo
nel body di `POST /sessions`.

### #4 – Health check non loggati
`logging_config.HealthCheckFilter` filtra le righe contenenti `/health`
da tutti i logger (incluso `uvicorn.access`). Controllabile via
`LOG_HEALTH_CHECKS=true` per debug temporaneo.

### #5 – Nomi tabelle DynamoDB configurabili
Tutti i riferimenti a DynamoDB usano `settings.dynamodb_sessions_table`
letta dall'env var `DYNAMODB_SESSIONS_TABLE`. Zero hardcoding.

---

## Setup Slack App

1. Vai su https://api.slack.com/apps e crea una nuova app.
2. **OAuth & Permissions** → Bot Token Scopes: `chat:write`, `reactions:add`.
3. **Event Subscriptions** → abilita, imposta Request URL:
   `https://<tuo-alb>/slack/events`
4. Subscribe to bot events: `message.im`, `message.channels`, `app_mention`.
5. Installa l'app nel workspace e copia `Bot User OAuth Token`.
6. Copia il `Signing Secret` dalla sezione Basic Information.

---

## Sviluppo locale

```bash
# Copia e compila il file di configurazione
cp .env.example .env
# Edita .env con i tuoi valori

# Installa dipendenze
pip install -r requirements.txt -r requirements-dev.txt

# Esegui i test
pytest tests/ -v

# Avvia il server locale (usa ngrok per esporre a Slack)
uvicorn src.app:app --reload --port 8000
ngrok http 8000
```

---

## CI/CD

```
git push origin main
        │
        ├─► [CI] pytest → coverage ≥ 80%
        │
        └─► [Deploy] (solo su main)
                ├─► pytest (gate)
                ├─► docker build + push ECR (tag = commit SHA)
                └─► ECS deploy (rolling update)
```

Secrets GitHub Actions da configurare:
- `AWS_ROLE_ARN`
- `ECR_REPOSITORY`
- `ECS_CLUSTER`
- `ECS_SERVICE`
- `ECS_TASK_DEFINITION`
