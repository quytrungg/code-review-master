export type ReviewStatus = "running" | "draft" | "in_discussion" | "applied" | "failed";
export type ReviewVerdict = "APPROVE" | "REQUEST_CHANGES" | "COMMENT";
export type MessageRole = "assistant" | "user" | "system";
export type ThreadOrigin = "AI_GENERATED" | "GITHUB_EXISTING";
export type ThreadStatus = "active" | "needs_response" | "applied" | "resolved";
export type RoundStatus = "drafting" | "pending_apply" | "published" | "resolved_no_reply";

export type VcsProvider = "github" | "gitlab";
export type LLMProvider = "claude" | "openai" | "ollama_cloud" | "ollama_local";

export interface VersionControlKey {
  id: number;
  provider: string;
  base_url: string | null;
  label: string | null;
  token_masked: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  token?: string | null;
}

export interface LLMKey {
  id: number;
  provider: string;
  base_url: string | null;
  default_model: string | null;
  label: string | null;
  api_key_masked: string | null;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
  api_key?: string | null;
}

export interface ActiveKeySummary {
  id: number;
  provider: string;
  label: string | null;
  base_url: string | null;
  secret_masked: string | null;
  default_model?: string | null;
}

export interface AppSettings {
  version_control_key_id: number | null;
  llm_key_id: number | null;
  version_control: ActiveKeySummary | null;
  llm: ActiveKeySummary | null;
  needs_setup: boolean;
  updated_at: string | null;
  version_control_token?: string | null;
  llm_api_key?: string | null;
}

export interface SettingsUpdate {
  version_control_key_id?: number | null;
  llm_key_id?: number | null;
}

export interface KeyTestResult {
  ok: boolean;
  detail: string;
  metadata: Record<string, unknown> | null;
}

export interface VersionControlKeyCreate {
  provider: VcsProvider;
  token: string;
  base_url?: string | null;
  label?: string | null;
}

export interface LLMKeyCreate {
  provider: LLMProvider;
  api_key?: string | null;
  base_url?: string | null;
  default_model?: string | null;
  label?: string | null;
}

export interface ConnectionResult {
  target: string;
  ok: boolean;
  detail: string;
  metadata: Record<string, unknown> | null;
}

export interface ConnectionTestResponse {
  results: ConnectionResult[];
}

export interface ModelOption {
  id: string;
  label: string;
  provider: "claude" | "openai" | "ollama-cloud" | "ollama-local";
  available: boolean;
  note?: string | null;
}

export interface ModelCatalog {
  models: ModelOption[];
  preferred: string | null;
  skills: string[];
}

export interface ThreadMessage {
  id: number;
  role: MessageRole;
  content: string;
  round_number: number;
  is_external: boolean;
  author: string | null;
  created_at: string | null;
}

export interface ThreadRound {
  id: number;
  round_number: number;
  inbound_github_comment_id: number | null;
  inbound_author: string | null;
  inbound_body: string | null;
  final_summary: string | null;
  status: RoundStatus;
  published_github_comment_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ReviewThread {
  id: number;
  review_id: number;
  ordinal: number;
  origin: ThreadOrigin;
  github_root_comment_id: number | null;
  original_author: string | null;
  current_round: number;
  thread_status: ThreadStatus;
  file_path: string;
  line_number: number;
  diff_hunk: string;
  side: "RIGHT" | "LEFT";
  summary: string | null;
  dropped: boolean;
  created_at: string | null;
  messages: ThreadMessage[];
  rounds: ThreadRound[];
}

export interface Foundation {
  id: string;
  label: string;
  is_default: boolean;
  file_count: number;
  total_chars: number;
  files: string[];
}

export interface SkillsResponse {
  default: string;
  uploads_enabled: boolean;
  foundations: Foundation[];
}

export interface SkillFileUpload {
  path: string;
  foundation: string;
  bytes: number;
}

export interface CreateReviewAccepted {
  id: number;
  status: ReviewStatus;
  skill_foundation: string | null;
}

export interface ProgressEvent {
  seq: number;
  ts: string;
  stage: string;
  label: string;
  detail: string | null;
  level: "info" | "warn" | "error";
  progress: number | null;
  data?: Record<string, unknown> | null;
}

export interface CodeReviewSummary {
  id: number;
  pr_url: string;
  vcs: string;
  pr_title: string | null;
  pr_number: number | null;
  repo_full_name: string | null;
  model_used: string | null;
  skill_foundation: string | null;
  status: ReviewStatus;
  verdict: ReviewVerdict | null;
  thread_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface DiscussResultItem {
  thread_id: number;
  ok: boolean;
  error: string | null;
  references: number[];
}

export interface AuthUser {
  id: number;
  email: string;
  created_at: string | null;
}

export interface ThreadOption {
  ordinal: number;
  file_path: string;
  line_number: number;
  excerpt: string;
}

export interface DiscussResponse {
  review: CodeReviewDetail;
  results: DiscussResultItem[];
  opinion_refreshed: boolean;
  warnings: string[];
}

export interface ApplyResponse {
  review: CodeReviewDetail;
  github_review_url: string | null;
  comments_posted: number;
  replies_posted: number;
  summarised: boolean;
  dropped: number[];
  warnings: string[];
}

export interface SyncResponse {
  review: CodeReviewDetail;
  new_threads: number;
  new_rounds: number;
  warnings: string[];
}

export type RoundDecision = "accept" | "push_back";

export interface RoundDecisionResponse {
  review: CodeReviewDetail;
  warnings: string[];
}

export interface CodeReviewDetail extends CodeReviewSummary {
  commit_id: string | null;
  error: string | null;
  notes: string | null;
  suggested_verdict: ReviewVerdict | null;
  confidence_percentage: number | null;
  suggested_verdict_note: string | null;
  github_review_url: string | null;
  threads: ReviewThread[];
  warnings: string[];
}
