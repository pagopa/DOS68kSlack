# DOS68K Slack Bot

A Slack bot that exposes the **DOS68K** PagoPA chatbot to internal users.
It handles per-user sessions and supports RAG-based responses with source links.

---

## Architecture

```
Slack User
     │  message
     ▼
Slack Events API
     │  POST /slack/events  (HTTPS)
     ▼
Application Load Balancer (AWS)
     │
     ▼
ECS Fargate – dos68k-slack-bot (FastAPI + Uvicorn)
     │
     └──► DOS68K Chatbot API (API Gateway + existing ECS)
               POST /sessions
               POST /queries/{sessionId}
               GET  /sessions/{sessionId}
               GET  /sessions/all
               DELETE /sessions/{sessionId}
```

**Why ECS Fargate instead of Lambda?**

The RAG-based chatbot can take > 3 seconds to respond, while Slack requires
an HTTP ACK within 3 seconds. With ECS Fargate + FastAPI `BackgroundTasks`,
the bot acknowledges Slack immediately and processes the query asynchronously,
with no additional infrastructure needed. Lambda would require an SQS queue
and a separate consumer function to achieve the same result.

Additionally, the active session mapping (`_active_sessions`) lives in memory
for the duration of the container — something Lambda cannot provide across
invocations.

---

## AWS Components

| Component | Purpose |
|---|---|
| **ECS Fargate** | Bot hosting (scalable, no server management) |
| **ECR** | Docker image registry |
| **Application Load Balancer** | TLS termination + routing to ECS |
| **Secrets Manager** | `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `CHATBOT_API_KEY` |
| **CloudWatch Logs** | Centralised logging; health check calls excluded by default |
| **IAM (OIDC)** | GitHub Actions authenticates to AWS without static credentials |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SLACK_BOT_TOKEN` | – | Slack OAuth token (from Secrets Manager) |
| `SLACK_SIGNING_SECRET` | – | Slack signing secret (from Secrets Manager) |
| `CHATBOT_API_KEY` | – | DOS68K API key (from Secrets Manager) |
| `CHATBOT_BASE_URL` | – | Chatbot backend base URL |
| `LOG_HEALTH_CHECKS` | `false` | Set to `true` to include `/health` calls in logs |
| `LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Bot Commands

| Command | Description |
|---|---|
| Any text | Sends the message to the chatbot on the active session. Creates a new session automatically if none is active. |
| `new` | Creates a new DOS68K session and sets it as active |
| `list` | Lists all existing sessions with their IDs |
| `resume <id>` | Resumes a previous session by ID |
| `help` | Shows available commands |

**RAG responses** automatically include a *Sources* section at the end of the
message, with clickable links to the documents used to generate the answer.

---

## Session Management

Active sessions are stored in a Python in-memory dictionary (`_active_sessions`),
mapping each Slack user ID to their current DOS68K session ID.

- Sessions **do not persist** across container restarts.
- After a restart, users can run `list` + `resume <id>` to pick up a previous session.
- If scaling horizontally to multiple ECS tasks, replace `_active_sessions`
  with a shared external cache (e.g. **ElastiCache Redis**).

**Event deduplication**: Slack retries events if no response is received within
3 seconds. The bot deduplicates by `event_id`, ignoring retries of already
processed events (TTL: 5 minutes).

---

## Slack App Setup

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app (**From scratch**).
2. **OAuth & Permissions → Bot Token Scopes** — add:
   - `chat:write`, `im:write`, `im:read`, `im:history`
   - `channels:history`, `groups:history`, `groups:read`
   - `app_mentions:read`
3. **Event Subscriptions** → enable, set Request URL to `https://<your-alb>/slack/events`.
4. **Subscribe to bot events** — add: `message.im`, `message.channels`, `message.groups`, `app_mention`.
5. **App Home → Show Tabs** → enable **Messages Tab** → check *Allow users to send Slash commands and messages from the messages tab*.
6. **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-...`).
7. Copy the **Signing Secret** from **Basic Information → App Credentials**.

> ⚠️ Reinstall the app every time you modify OAuth scopes and update `SLACK_BOT_TOKEN` in `.env`.

---

## Local Development

```bash
# 1. Clone the repo and enter the project directory
git clone <repo-url>
cd dos68k-slack-bot

# 2. Install dependencies (creates .venv automatically)
uv sync

# 3. Configure environment variables
cp .env.example .env
# Edit .env with your actual values

# 4. Run tests
uv run pytest tests/ -v

# 5. Start the server
uv run uvicorn src.app:app --reload --port 8000

# 6. Expose locally via ngrok (in a separate terminal)
ngrok http 8000
# Copy the HTTPS URL and set it as the Request URL in Slack Event Subscriptions
```

---

## CI/CD

```
git push origin main
        │
        ├─► [CI] pytest → coverage ≥ 80%
        │
        └─► [Deploy] (main branch only)
                ├─► pytest (gate — build blocked if tests fail)
                ├─► docker build + push to ECR (tag = commit SHA)
                └─► ECS rolling update
```

Required GitHub Actions secrets:

| Secret | Description |
|---|---|
| `AWS_ROLE_ARN` | IAM Role ARN with ECR + ECS permissions (OIDC) |
| `ECR_REPOSITORY` | Full ECR URI (e.g. `123456789.dkr.ecr.eu-south-1.amazonaws.com/dos68k-slack-bot`) |
| `ECS_CLUSTER` | ECS cluster name |
| `ECS_SERVICE` | ECS service name |
| `ECS_TASK_DEFINITION` | ECS task definition name |