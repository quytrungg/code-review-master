# MISSION

You are an expert Full-Stack Software Engineer and AI Systems Architect. Your objective is to build a local-first, interactive "AI Code Review Assistant" composed of a React frontend and a Python (FastAPI) backend. The tool connects GitHub PRs with local or cloud LLMs (Ollama / Claude), injects custom local code-review skills, and enables an interactive side-by-side discussion workflow before publishing the final review back to GitHub.

---

# OPERATING PROTOCOL: PLAN-FIRST WORKFLOW (MANDATORY)

Before implementing code for any phase, you **must adhere to a strict two-stage process**:

1. **Stage A: Implementation Plan Document:**
   - For every phase (Phases 1 through 5), you must first create a standalone markdown file under `docs/plans/phase_<N>_plan.md`.
   - Each phase plan must contain:
     - **Objective & Scope:** Clear definition of what will and will not be built.
     - **High-Level Design & Architectural Diagrams:** At least one clear diagram written in valid **Mermaid syntax** (`flowchart`, `sequenceDiagram`, `stateDiagram-v2`, or `classDiagram`) explaining data flow, component hierarchy, or API interaction.
     - **API Contracts & Data Schemas:** Exact JSON request/response formats, models, and type definitions.
     - **Target File Map:** List of new files to create and existing files to modify with their specific responsibilities.
     - **Step-by-Step Implementation Steps:** Granular breakdown of implementation order.
     - **Verification & Acceptance Criteria:** Exact manual or automated verification checks.
2. **Stage B: Implementation:**
   - Only after generating the plan markdown document may you proceed to execute the code for that phase.

---

# TECH STACK & SYSTEM ARCHITECTURE

* **Frontend:** React 18+ (Vite, TypeScript, Tailwind CSS, Lucide-react, Shadcn/UI primitives).
* **Backend:** Python 3.11+ (FastAPI, Uvicorn, Pydantic v2).
* **Database & ORM:**
  * SQLite (local file: `app.db`) for lightweight, local-first operation.
  * SQLAlchemy 2.0 with **Alembic migrations**.
  * Abstract database connection via a `DATABASE_URL` environment variable using dialect-agnostic models so the database can seamlessly migrate to **PostgreSQL** by switching the connection string without code refactoring.
* **AI Integrations:** Anthropic Python SDK (`anthropic`), Ollama client (`ollama` or async `httpx`).
* **GitHub Integration:** GitHub REST API v3 using `httpx` or `PyGithub`.
* **Project Structure:**
  ```text
  ├── backend/
  │   ├── app/
  │   │   ├── api/routes/          # settings.py, reviews.py, github.py, llm.py
  │   │   ├── core/config.py       # Settings & environment variables
  │   │   ├── db/session.py        # SQLAlchemy engine & session factory
  │   │   ├── models/              # SQLAlchemy DB models
  │   │   ├── schemas/             # Pydantic schemas
  │   │   └── services/            # github_service, llm_service, skill_loader
  │   ├── alembic/                 # Database migrations (PostgreSQL-ready)
  │   ├── code-review/             # Local predefined skill folder (.md / .txt files)
  │   ├── requirements.txt
  │   └── main.py
  ├── frontend/
  │   ├── src/
  │   │   ├── components/          # ReviewSplitView, CommentBox, CodeSnippetBox, Navbar
  │   │   ├── pages/               # SettingsPage, DashboardPage, ReviewDetailPage
  │   │   ├── services/api.ts      # Axios or Fetch client wrapper
  │   │   └── types/               # TypeScript interfaces
  │   ├── package.json
  │   └── tailwind.config.js
  ├── docs/
  │   └── plans/                   # Implementation plan markdowns for each phase
  ```

---

# DATA MODEL SPECIFICATIONS (SQLAlchemy / Alembic)

Ensure all models use standard PostgreSQL-compatible column types (e.g., use `Text` rather than dialect-specific strings, `DateTime(timezone=True)`, `JSON` or structured relational tables):

1. **`Settings`**:
   * `id` (Integer/UUID, PK)
   * `github_token` (Text, nullable)
   * `claude_api_key` (Text, nullable)
   * `ollama_base_url` (Text, default: `http://localhost:11434`)
   * `ollama_model` (Text, default: `llama3`)
   * `updated_at` (DateTime)

2. **`CodeReview`**:
   * `id` (UUID/Integer, PK)
   * `pr_url` (Text, not null)
   * `pr_title` (Text)
   * `pr_number` (Integer)
   * `repo_full_name` (Text)
   * `commit_id` (Text) — latest HEAD commit SHA for inline commenting
   * `model_used` (Text)
   * `status` (Enum/String: `draft`, `in_discussion`, `applied`)
   * `verdict` (Enum/String: `APPROVE`, `REQUEST_CHANGES`, `COMMENT`, nullable)
   * `created_at`, `updated_at` (DateTime)

3. **`ReviewThread`**:
   * `id` (UUID/Integer, PK)
   * `review_id` (FK to `CodeReview.id`, cascade delete)
   * `file_path` (Text)
   * `line_number` (Integer)
   * `diff_hunk` (Text) — the surrounding code snippet / lines of code (LOC)
   * `created_at` (DateTime)

4. **`ThreadMessage`**:
   * `id` (UUID/Integer, PK)
   * `thread_id` (FK to `ReviewThread.id`, cascade delete)
   * `role` (Enum/String: `assistant`, `user`, `system`)
   * `content` (Text)
   * `created_at` (DateTime)

---

# DETAILED FEATURE REQUIREMENTS

## 1. Settings & Token Management (`/settings`)
* Form to view, add, edit, or delete:
  * GitHub Personal Access Token (classic with `repo` scope or fine-grained with Pull Request Read/Write).
  * Claude API Key (`sk-ant-...`).
  * Ollama Base URL and active model name.
* Backend API endpoints: `GET /api/settings`, `PUT /api/settings`, `POST /api/settings/test-connection` (to verify GitHub auth and Ollama availability).
* Persist values in the database. Provide UI options to clear or mask stored secrets.

## 2. Main Dashboard (`/` or `/reviews`)
* Table/Grid listing past reviews: PR title, repository name, date, model used, and status badge (`Draft`, `Applied`).
* **"New Code Review" Section:**
  * Input field for GitHub PR URL (e.g., `https://github.com/owner/repo/pull/123`).
  * Dynamic model selection dropdown populated based on configured credentials:
    * If Claude key is configured: options for Claude models (e.g., Sonnet, Haiku).
    * If Ollama is configured: fetch installed local models dynamically via `GET {ollama_base_url}/api/tags`.
  * "Start Review" button that triggers the ingestion pipeline.

## 3. Skill Injection & AI Review Pipeline (Backend)
* **Local Skill Ingestion:**
  * Scan the `./code-review` directory on the backend for all `.md` and `.txt` files (e.g., `security.md`, `style.md`, `performance.md`).
  * Aggregate these files into a master system prompt detailing the exact guidelines, review conventions, and standards the AI must enforce.
* **GitHub PR Parsing:**
  * Parse `owner`, `repo`, and `pull_number` from the URL.
  * Fetch PR metadata (including HEAD commit SHA) and git diff patch (`Accept: application/vnd.github.v3.diff`).
  * Parse files and diff hunks to identify changed lines.
* **AI Structured Output:**
  * Send the system skills, PR context, and diff hunks to the selected model.
  * Enforce a strict JSON output schema:
    ```json
    [
      {
        "filePath": "src/services/auth.py",
        "lineNumber": 42,
        "diffHunk": "def verify_token(token):\n-   return jwt.decode(token, verify=False)\n+   return jwt.decode(token, key=SECRET, algorithms=['HS256'])",
        "initialComment": "Critical security risk: Disabling JWT signature verification exposes authentication to tampering."
      }
    ]
    ```
  * Persist the structured response into `ReviewThread` and `ThreadMessage` tables.

## 4. Split-Pane Interactive Detail Page (`/reviews/:id`)
* **Layout:** Responsive 50/50 horizontal split-pane (left and right panels).
* **Left Panel (LOC & Context):**
  * Render an isolated, styled code container for each `ReviewThread`.
  * Display the file path, targeted line number, and syntax-highlighted diff chunk (`diffHunk`).
  * Must visually align or link with the corresponding comment card on the right panel.
* **Right Panel (Interactive Discussion):**
  * Each thread displays an interactive card matching the left code box:
    * Top: Initial AI feedback (Markdown supported).
    * Middle: Conversation history for this specific thread.
    * Bottom: Text area for user comments/questions (e.g., *"Can we use an allowlist here instead?"*).
* **Drafting State:** Typing into these comment boxes updates local React state only. No LLM requests are made while typing.

## 5. Bulk Review Processing ("Submit Responses")
* Positioned in a sticky footer at the bottom of the review page.
* **Action:**
  * Gathers all threads containing unsent user drafts.
  * Sends a bulk payload `POST /api/reviews/{id}/discuss` with the updated thread messages.
  * Backend runs concurrent queries to the chosen LLM for each updated thread, providing the file context, system skills, and thread conversation history.
  * The model responds directly to the user's inquiry, updating the thread with a new `assistant` message.
  * The UI updates dynamically, rendering the AI's reply directly inside each respective comment box.

## 6. Review Finalization ("Apply Review to GitHub")
* Located in the sticky footer next to the "Submit Responses" button.
* UI elements:
  * Action selector: Radio/Toggle for review event: `REQUEST_CHANGES`, `APPROVE`, or `COMMENT`.
  * Summary review body: Optional high-level overall summary note.
* **Execution via GitHub API:**
  * When "Apply" is clicked:
    1. For each `ReviewThread`, determine the final agreed-upon conclusion (the last message or an AI-summarized version of the thread).
    2. Format inline review comments using GitHub's Pull Request Review API:
       `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`
       Payload:
       ```json
       {
         "commit_id": "<HEAD_COMMIT_SHA>",
         "event": "REQUEST_CHANGES",
         "body": "Overall automated review completed with interactive human oversight.",
         "comments": [
           {
             "path": "src/services/auth.py",
             "line": 42,
             "side": "RIGHT",
             "body": "**AI Review Conclusion:** Critical security risk resolved by updating algorithm verification."
           }
         ]
       }
       ```
    3. Update the local review status to `applied`.
    4. Provide user feedback with a direct link to the submitted GitHub review.

---

# IMPLEMENTATION ROADMAP & PHASE WORKFLOW

Before coding each phase, generate `docs/plans/phase_<N>_plan.md` featuring a detailed technical breakdown and Mermaid diagrams.

* **Phase 1: Project Setup, Database Layer & Token Settings**
  * *Plan Output:* `docs/plans/phase_1_plan.md` (must include an Entity-Relationship / DB Architecture diagram in Mermaid and an API flow diagram).
  * *Implementation:* Setup FastAPI app, Vite React project, SQLAlchemy ORM with SQLite (PostgreSQL-migratable), Alembic migrations, Settings endpoints, and frontend Settings UI.

* **Phase 2: Ingestion, Local Skill Reader & GitHub Integration**
  * *Plan Output:* `docs/plans/phase_2_plan.md` (must include a Sequence Diagram in Mermaid tracing PR ingestion, local skill loading from `./code-review`, LLM prompt construction, and structured JSON parsing).
  * *Implementation:* Read local skill directory, fetch PR diff via GitHub API, invoke Claude/Ollama, parse structured review response, and store in the database.

* **Phase 3: Dual-Panel Interactive Workspace UI**
  * *Plan Output:* `docs/plans/phase_3_plan.md` (must include a UI Component Hierarchy & State Flow diagram in Mermaid).
  * *Implementation:* Build the 50/50 split layout in React, syntax-highlighted diff boxes on the left, interactive discussion thread cards on the right, and draft state management.

* **Phase 4: Discussion Loop & Bulk Submit**
  * *Plan Output:* `docs/plans/phase_4_plan.md` (must include a Sequence Diagram in Mermaid showing bulk payload aggregation, parallel LLM queries, and optimistic/rendered UI updates).
  * *Implementation:* `POST /api/reviews/{id}/discuss` endpoint, concurrent LLM query orchestration, conversation state updates, and bulk UI synchronization.

* **Phase 5: GitHub Application & Export Review**
  * *Plan Output:* `docs/plans/phase_5_plan.md` (must include an End-to-End State Machine / Sequence Diagram in Mermaid showing final comment collation, GitHub review creation, and status transitions).
  * *Implementation:* "Apply Review" button handler, GitHub PR Review API submission with inline diff comments and verdict (`APPROVE` / `REQUEST_CHANGES`), and error recovery.

---

# INITIATION INSTRUCTION

Acknowledge this mission. **Do not write application code yet.** 

Begin by creating `docs/plans/phase_1_plan.md` containing the complete implementation plan and Mermaid design diagrams for **Phase 1: Project Setup, Database Layer & Token Settings**.