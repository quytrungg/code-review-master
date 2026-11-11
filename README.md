# AI Code Review Assistant

A local-first, interactive pull-request reviewer. Point it at a GitHub PR or GitLab MR, let a model review the diff against **your own review standards**, discuss the findings in a side-by-side workspace, then publish the agreed conclusion as one review with inline comments.

Use **Ollama Cloud** (default), **Claude**, **OpenAI/Codex**, or a **local Ollama daemon**. Nothing leaves your machine except the diff and prompts sent to the model you choose; credentials, reviews, and conversations stay in your own database.

## Highlights

- **Your standards, not generic advice** — inject a local markdown skill library into each review, with rules selected for the files that changed.
- **Findings anchored to real code** — every finding is mapped to a valid diff line, with its code context rebuilt from the actual PR diff.
- **A review you can argue with** — discuss findings, reference other threads with `#N`, accept a conclusion, or push back before anything is published.
- **Existing conversations included** — import current PR comments, sync new replies, and manage AI findings and human discussions in one workspace.
- **Publish only what you approve** — accepted findings become one review with inline comments; rejected or withdrawn findings stay unpublished.
- **Follow new pushes automatically** — watch a PR and review only the delta when its head commit changes.
- **Understand model usage** — track calls, tokens, latency, estimated cost, acceptance rate, and push-back rate per review and across models.

## How it works

```text
GitHub PR / GitLab MR
        │
        ▼
Fetch metadata + diff ──► Parse files and line numbers
        │
        ▼
Select relevant review skills ──► Ask the configured model
        │
        ▼
Anchor and validate findings
        │
        ▼
Split-pane workspace: code ◄──► discussion
        │
        ├── Accept, edit, or push back
        ├── Import and answer existing PR threads
        └── Re-check the AI verdict after discussion
        │
        ▼
Publish one review + accepted inline comments
```

A typical session looks like this:

1. Paste a PR or MR URL and choose a model and skill foundation.
2. Watch ingest progress while the app fetches the diff, loads review rules, and generates findings.
3. Inspect each finding beside its anchored code hunk.
4. Discuss uncertain findings, sync incoming PR comments, and accept or reject each conclusion.
5. Choose `REQUEST_CHANGES`, `APPROVE`, or `COMMENT` and apply the review.
6. Optionally watch the PR so later pushes receive a linked delta review.

## Requirements

- Python 3.12 and Node.js 18+
- PostgreSQL 14+ (SQLite is also supported for local trials and tests)
- A GitHub token or GitLab personal access token
- An Ollama Cloud, Anthropic, or OpenAI API key, or a running local Ollama daemon

## Quick start

### 1. Start the backend

```bash
cd backend
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
createdb code_review
cp .env.example .env
uvicorn app.main:app --reload --reload-exclude 'tests/*.py' --reload-exclude 'alembic/*.py' \
  --reload-exclude '*.db' --port 8000
```

The default database is `postgresql+psycopg://localhost:5432/code_review`. Startup applies the Alembic migrations automatically. For a disposable SQLite setup, set `DATABASE_URL=sqlite:///./app.db` in `backend/.env`.

The API is available at `http://127.0.0.1:8000/api/health`, with interactive OpenAPI documentation at `http://127.0.0.1:8000/docs`.

### 2. Start the frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to the backend on port 8000.

### 3. Configure and review

On first launch, the setup guide asks for:

1. **Version control** — add a GitHub or GitLab token.
2. **Model provider** — add a hosted-provider API key or a local Ollama base URL.
3. **First review** — return to the dashboard, paste a PR/MR URL, select a model, and choose **Start review**.

Credentials are encrypted at rest when `CREDENTIALS_ENCRYPTION_KEY` is configured. Generate a key with:

```bash
cd backend
python scripts/generate_encryption_key.py
```

Add the generated value to `backend/.env` before storing credentials.

## Docker

The Docker image includes the API, compiled frontend, and default skill library:

```bash
docker build -t code-review-master:dev .
docker run --rm -p 8000:8000 -v code-review-data:/data code-review-master:dev
```

Open `http://127.0.0.1:8000`. The `/data` volume stores the SQLite database, uploaded skill foundations, and the editable default skill library.

## Project layout

```text
backend/    FastAPI, SQLAlchemy, Alembic, review pipeline, providers, and tests
frontend/   React + TypeScript workspace, dashboard, settings, and analytics
code-review/  Default markdown review standards injected into model prompts
```
