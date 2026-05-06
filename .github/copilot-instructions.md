# DOS68K Slack Bot – Copilot Instructions

## Quick Commands

### Build & Test
```bash
# Install all dependencies (production + dev)
uv sync

# Run all tests
uv run pytest tests/ -v

# Run a single test by name
uv run pytest tests/test_all.py::TestSlackVerifier::test_valid_signature_passes -v

# Run tests with coverage (must meet 80% threshold for CI)
uv run pytest tests/ --cov=src --cov-report=term-missing --cov-fail-under=80 -v

# Run tests as they execute in CI/CD
uv run pytest tests/ \
  --cov=src \
  --cov-report=term-missing \
  --cov-report=xml:coverage.xml \
  --cov-fail-under=80 \
  -v

# Local development server (use with ngrok for Slack integration)
uv run uvicorn src.app:app --reload --port 8000
```

### Dependency Management
```bash
uv add <package>              # add a production dependency
uv add --group dev <package>  # add a dev dependency
uv remove <package>           # remove a dependency
uv lock                       # regenerate uv.lock after editing pyproject.toml
uv sync                       # install all deps from lock file (incl. dev)
uv sync --no-dev              # install production deps only
```

### CI/CD Pipeline

The pipeline has two workflows:

1. **CI** (`.github/workflows/ci.yml`): Runs on all pushes and PRs to `main`/`develop`
   - Unit tests must pass before deployment
   - Coverage must be ≥ 80%

2. **Deploy** (`.github/workflows/deploy.yml`): Runs on push to `main` only
   - Tests must pass before build starts (`needs: test`)
   - Docker image tagged with commit SHA and pushed to ECR
   - ECS service updated with rolling deployment

## Architecture

### High-Level Flow

```
Slack User → Slack Events API → ALB (AWS) → ECS Fargate (FastAPI + Uvicorn)
                                                    ↓
                                           - Verify Slack signature
                                           - ACK immediately (< 3s)
                                           - Process in background
                                                    ↓
                                           DynamoDB (session mapping)
                                           DOS68K Chatbot API
                                           Slack Web API (send responses)
```

### Why ECS Fargate (not Lambda)?

DOS68K's RAG chatbot can take > 3 seconds to respond. Slack requires acknowledgment within 3 seconds or retries the request. ECS allows us to:
- Return HTTP 200 immediately to Slack
- Process the actual query asynchronously in a background task
- Avoid Slack's retry logic (which Lambda would struggle with under 3-second timeout)

### Key Components

| Component | Purpose |
|-----------|---------|
| **FastAPI App** (`src/app.py`) | HTTP server with two endpoints: `/health` and `/slack/events` |
| **SlackHandler** (`src/slack_handler.py`) | Orchestrates event verification, session management, and message routing |
| **DOS68KClient** (`src/chatbot_client.py`) | HTTP client for the DOS68K chatbot backend |
| **DynamoDB** | Stores `slack_user_id → session_id` mappings with TTL (configurable, default 3600s) |
| **Slack Verifier** (`src/slack_verifier.py`) | Cryptographically verifies request signatures using HMAC-SHA256 |
| **Settings** (`src/config.py`) | Pydantic BaseSettings – loads all config from environment variables |

## Code Patterns

### Async/Await Pattern

All I/O operations use `async def` with `await`:

```python
# ✓ Correct
async def process(self, headers: dict, body: str):
    response = await self.chatbot_client.query(...)

# ✗ Wrong
def process(self, headers: dict, body: str):
    response = await self.chatbot_client.query(...)  # SyntaxError
```

### ACK + Background Task Pattern

FastAPI's `BackgroundTasks` ensures immediate response to Slack while processing continues:

```python
@app.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks):
    # 1. Verify and handle challenge synchronously
    ack, status_code = await slack_handler.ack(headers, body_str)
    if ack is not None:
        return Response(content=ack, status_code=status_code)
    
    # 2. Return 200 OK immediately
    # 3. Process in background (won't block response)
    background_tasks.add_task(slack_handler.process, headers, body_str)
    return Response(content='{"ok": true}', status_code=200)
```

### Configuration Loading

All environment variables are validated via Pydantic's `BaseSettings`. Required variables will fail loudly at startup if missing:

```python
from src.config import settings

# These are validated as required (no default):
settings.slack_bot_token
settings.slack_signing_secret
settings.chatbot_api_key

# These have defaults:
settings.log_health_checks  # default: False
settings.log_level  # default: "INFO"
```

Environment variables are case-insensitive due to `case_sensitive = False` in Settings.Config.

### Session Deduplication

Slack can retry the same event if no response is received within 3 seconds. The handler tracks processed event IDs in memory with a 5-minute TTL to prevent duplicate processing:

```python
_processed_events: dict[str, float] = {}  # event_id → timestamp
_EVENT_TTL = 300  # 5 minutes
```

This deduplication is **in-memory only** – it does not persist across container restarts.

### Active Session Tracking

The current session for each Slack user is tracked in memory. Users can:
- `new` – Create a new session (becomes active)
- `resume <id>` – Switch to a previous session
- `list` – Show all sessions
- Any other message → sent to the currently active session (or auto-create one)

Like event deduplication, active session state is **in-memory only**.

## Environment Variables

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `SLACK_BOT_TOKEN` | Yes | – | OAuth token from Slack App (starts with `xoxb-`) |
| `SLACK_SIGNING_SECRET` | Yes | – | Signing secret from Slack App's "Basic Information" |
| `CHATBOT_BASE_URL` | Yes | – | Base URL of the DOS68K chatbot API |
| `CHATBOT_API_KEY` | Yes | – | API key for DOS68K chatbot |
| `DYNAMODB_SESSIONS_TABLE` | No | `dos68k-slack-sessions` | DynamoDB table name for session mappings |
| `SLACK_SESSION_TTL_SECONDS` | No | `3600` | TTL for sessions (in seconds) |
| `LOG_HEALTH_CHECKS` | No | `false` | If `true`, logs `/health` requests (set to `true` for debugging) |
| `LOG_LEVEL` | No | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `AWS_REGION` | No | `eu-south-1` | AWS region for DynamoDB and other services |

## Testing

### Test Structure

Tests are located in `tests/test_all.py` and use `pytest` with mocking:

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    """Automatically inject test environment variables for every test."""
    monkeypatch.setenv("SLACK_SIGNING_SECRET", "test_secret_abc123")
    # ...
```

### Key Testing Patterns

1. **Slack Signature Verification**: Tests verify HMAC-SHA256 signatures using a helper function that generates valid timestamps and signatures.

2. **Async Testing**: Use `pytest-asyncio` for async test functions:
   ```python
   @pytest.mark.asyncio
   async def test_some_async_operation():
       result = await some_async_function()
       assert result == expected
   ```

3. **Mocking**: Use `unittest.mock` to mock Slack API calls and DynamoDB operations. Tests do not require AWS credentials or live Slack workspace.

### Coverage Requirements

- Minimum coverage: **80%**
- Report format: Both terminal and XML (for codecov.io upload)
- Coverage gates the CI pipeline – deploy will not proceed if coverage falls below threshold

## Logging

### Health Check Filter

`LoggingConfig.HealthCheckFilter` in `src/logging_config.py` removes logs for `/health` endpoint requests by default (they're high-volume and not useful).

To debug health checks:
```bash
LOG_HEALTH_CHECKS=true uvicorn src.app:app --reload
```

### Log Levels

- `DEBUG`: Detailed flow (event IDs, session transitions, API calls)
- `INFO`: Key milestones (bot started, session created, message processed)
- `WARNING`: Recoverable issues (Slack API errors, invalid signatures)
- `ERROR`: Unrecoverable issues (missing env vars, DynamoDB failures)

## Deployment

### Docker Image Tagging

Docker images are tagged with the **commit SHA** (`${{ github.sha }}`), not semantic versions. This ensures full traceability of what's running in production.

### Secrets Management

All secrets are stored in **AWS Secrets Manager** and injected into the ECS task as environment variables. Never commit `.env` with real values.

### ECS Deployment

After image push to ECR, the ECS service is updated with a rolling deployment strategy:
- Old tasks are gradually replaced with new tasks
- New image is pulled from ECR
- Health checks ensure only healthy tasks remain in load balancer

## Troubleshooting

### Common Issues

**"Invalid signing secret"** (401 response from Slack)
- Verify `SLACK_SIGNING_SECRET` matches exactly (get it from Slack App's "Basic Information")
- Check for extra spaces or whitespace in the secret

**"Session not found"** (ChatbotAPIError)
- Sessions are stored in DynamoDB with a TTL
- If session has expired, create a new one with `new` command

**Health checks not logging**
- By default, `/health` requests are filtered out. Set `LOG_HEALTH_CHECKS=true` to see them.

**Tests fail locally but pass in CI**
- Ensure all required env vars are set (see "Environment Variables" section)
- Check Python version: CI uses Python 3.12 (run `uv python install 3.12` if needed)
- Verify mock setup in tests matches your code changes
- Run `uv sync --frozen` to ensure your venv matches the lock file

## MCP Servers

This repository is configured to work with the following MCP servers for enhanced Copilot sessions:

### AWS Knowledge

The AWS Knowledge MCP server provides access to:
- AWS documentation and API reference
- Regional resource availability checks
- Service capabilities and examples

Use this when:
- Exploring ECS, DynamoDB, or Secrets Manager configurations
- Verifying AWS service limits or quotas
- Finding best practices for AWS services
- Checking regional availability of services
- Understanding IAM permissions and policies

**Example queries for AWS Knowledge:**
- "How do I configure DynamoDB TTL in boto3?"
- "What IAM permissions does ECS Fargate need for ECR access?"
- "What regions have Application Load Balancer?"
- "Lambda vs ECS trade-offs for this async pattern"

### GitHub

The GitHub MCP server provides access to:
- Repository issues and pull requests
- Commit history and changes
- GitHub Actions workflow logs
- Branch information
- File and commit details

Use this when:
- Reviewing related issues or PRs for context
- Understanding past changes to specific files
- Checking CI/CD pipeline status
- Verifying deployment history
- Finding who made specific changes and why

**Example queries for GitHub:**
- "Show me recent commits to src/slack_handler.py"
- "What issues are related to DynamoDB session management?"
- "Check the latest deploy workflow logs"
- "What was changed in the last 5 commits?"

## Copilot Cloud Agent Setup

When Copilot runs in your repository, it uses the `copilot-setup-steps.yml` workflow to prepare its environment:

1. Checks out your code
2. Installs uv (`astral-sh/setup-uv@v5`)
3. Installs Python 3.12 via `uv python install 3.12`
4. Installs all dependencies (production + dev) via `uv sync --frozen`
5. Verifies the installation with version checks

This ensures Copilot can immediately build, test, and lint your code without discovering dependencies on its own.

## File Structure

```
dos68k-slack-bot/
├── .github/
│   ├── copilot-instructions.md  (this file)
│   └── workflows/
│       ├── ci.yml               (test on all pushes/PRs)
│       ├── deploy.yml           (deploy on main)
│       ├── build-and-push.yml   (manual Docker build + push to GHCR)
│       └── copilot-setup-steps.yml  (Copilot environment setup)
├── src/
│   ├── __init__.py
│   ├── app.py                   (FastAPI entry point)
│   ├── config.py                (Pydantic settings)
│   ├── slack_handler.py         (event orchestration)
│   ├── slack_verifier.py        (signature verification)
│   ├── chatbot_client.py        (DOS68K API client)
│   └── logging_config.py        (logging setup)
├── tests/
│   └── test_all.py              (pytest suite)
├── pyproject.toml               (project metadata + all dependencies)
├── uv.lock                      (pinned dependency lock file)
├── Dockerfile
└── README.md
```
