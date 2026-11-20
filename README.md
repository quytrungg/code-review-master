# AI Code Review Assistant

A local-first, interactive pull-request reviewer. Point it at a GitHub PR or GitLab MR, let a model review the diff against **your own review standards**, discuss the findings in a side-by-side workspace, then publish the agreed conclusion as one review with inline comments.

Use **Ollama Cloud** (default), **Claude**, **OpenAI/Codex**, **OpenCode** (Zen or a Go subscription), or a **local Ollama daemon**. Nothing leaves your machine except the diff and prompts sent to the model you choose; credentials, reviews, and conversations stay in your own database.

## Highlights

- **Your standards, not generic advice** — inject a local markdown skill library into each review, with rules selected for the files that changed.
- **Findings anchored to real code** — every finding is mapped to a valid diff line, with its code context rebuilt from the actual PR diff.
- **A review you can argue with** — discuss findings, reference other threads with `#N`, accept a conclusion, or push back before anything is published. Disagree with the AI's verdict itself and it re-reads the review against your reasoning, then says whether it changed its mind. Replies stream token by token; stop the batch or retry one thread without losing what finished.
- **Existing conversations included** — import current PR comments, sync new replies, and manage AI findings and human discussions in one workspace.
- **Publish only what you approve** — accepted findings become one review with inline comments; rejected or withdrawn findings stay unpublished.
- **Follow new pushes automatically** — watch a PR and review only the delta when its head commit changes, or press **Check now** to review a push immediately instead of waiting for the poll.
- **Your standards can improve themselves** — let a model read your last 30 days of reviews and pushbacks in their comment threads, propose edits to the guideline files, review the diff, then apply them or clone them into a new foundation.
- **Understand model usage** — track calls, tokens, latency, estimated cost, acceptance rate, and push-back rate per review and across models.
- **Catch what a regex knows for certain** — optional deterministic packs flag committed token prefixes, private-key headers, conflict markers, debugger statements, `console.log`, and focused tests before the model runs, at zero tokens.
- **Let the queue move itself** — a standing policy reviews PRs in a repository that are waiting on you, on the same tick that watches already use.
- **Remember what you have flagged before** — every finding carries a normalised key, so search spans reviews, a finding shows prior matches in the same repository, and Analytics lists recurring patterns.
- **Compare models on the same diff** — re-run a review with a second model, priced before it starts, and read one merge view of both / only-A / only-B findings.

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
5. Choose `REQUEST_CHANGES`, `APPROVE`, or `COMMENT` and apply the review. An approval needs nothing
   accepted — the PR is the message — and a review that already posted comments can still approve the
   same pull request once.
6. Optionally watch the PR so later pushes receive a linked delta review. Watches are polled every
   ten minutes (or by the serverless cron); **Check now** beside the watch button runs that check
   straight away, and works on a paused watch too.

Review ingest has its own output budget (`LLM_REVIEW_MAX_TOKENS`, default `8192`) and disables reasoning on the OpenCode relay, so a reasoning model spends the call writing findings instead of deliberation.

## Requirements

- Python 3.12 and Node.js 18+
- PostgreSQL 14+ (SQLite is also supported for local trials and tests)
- A GitHub token or GitLab personal access token
- An Ollama Cloud, Anthropic, OpenAI, or OpenCode (Zen or Go) API key, or a running local Ollama daemon

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
3. **First review** — return to the dashboard and choose **New code review**, paste a PR/MR URL, select a model, and choose **Start review**. The list below it is paged 10 rows at a time (10/20/50/100), and the magnifier next to **Refresh** searches findings across every review.

The review runs in the background: leave the workspace whenever you like and keep reading the list, the PR inbox or anything else. The Reviews page refreshes itself while something is running, a review that finishes while you are away gets a dot on its row, and the **Reviews** tab shows how many finished reviews you have not opened yet. Opening the review clears it. The **PR Inbox** badge counts something else: open pull requests that need a first review, plus reviewed ones with a reply newer than your last review or comment. In the inbox those rows sit on top, reviewed items without new replies are labelled **Reviewed** at the bottom, and **Needs attention only** narrows the list to the badge's count. Cards page 10 at a time (switch to 20, 50 or 100), the GitHub link is the icon beside each PR title, and **Approve**, **Request changes** and **Comment** live under **Actions**. **Sync with GitHub** only discovers pull requests created in the last two months; anything older drops out of the inbox.

Claude has two credentials in **Settings → Model providers**: an Anthropic API key, or **Claude sign-in**. The sign-in opens claude.ai in a new tab (using the Claude Code OAuth client, so Anthropic's terms apply), and you paste the code it shows back here. The access and refresh tokens are encrypted in your local database, the refresh token never leaves the server, and an expiring token is renewed automatically before the next review, discussion or verdict call. Reconnect from the same panel if a sign-in is revoked.

Settings also has a **Beta features** card: experiments in development, switched on per account and stored with your settings. The first flag is *Push-back lessons* — when you push back on a finding, the app offers to record the lesson as a rule in a skill foundation. Turn the flag on, click Push back, and a dialog asks: **No** dismisses it and pushes back as usual; **Yes** drafts a reusable rule from the finding (editable), you pick the target foundation, and **Save lesson** writes it there as `lessons/<filetype>-<slug>.md` — so future reviews of the same file type load it.

Two more Settings cards have nothing to do with betas. **Deterministic checks** switches on the pre-pass packs (off by default): a matching line becomes an ordinary finding, discussable and publishable, and the model is told not to repeat it. **Standing policies** reviews PRs in a repository as they arrive in your inbox, at most *N* at a time and only for the involvement you choose; they run on the watch tick, so a deployment with no tick runs none.

The **Skills** tab has **Evolve from review history** in its header. The dialog picks the foundation and the model; the evidence is the last 30 days of review history — past reviews and the corrections you left in their comment threads. Nothing else is read, so the analysis works the same locally and on a hosted deployment. (The backend can still add a local CLI-agent folder to the prompt through `POST /api/skills/{foundation}/analyze-history` with `session_source`, but the dialog no longer offers it.) The analysis asks the model for **targeted edits** (`oldText` → `newText`) rather than a copy of every file, and it has its own output budget (`LLM_EVOLVE_MAX_TOKENS`) with reasoning disabled on the OpenCode relay, so a reasoning model cannot spend the whole answer on deliberation.

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
