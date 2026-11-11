export type ReviewStatus = "running" | "draft" | "in_discussion" | "applied" | "failed";
export type ReviewVerdict = "APPROVE" | "REQUEST_CHANGES" | "COMMENT";
export type InboxStatus = "needs_review" | "approved" | "request_changed" | "commented";
export type CachedPRInvolvement = "reviewer" | "assignee" | "author";
export type QuickReviewEvent = ReviewVerdict;
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
  // Soft monthly caps for Analytics; `null` means uncapped.
  monthly_token_budget: number | null;
  monthly_dollar_budget: number | null;
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
  monthly_token_budget?: number | null;
  monthly_dollar_budget?: number | null;
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

/** What one review's model calls cost, in counts only. */
export interface ReviewUsage {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  latency_ms: number;
}

export type LLMPurpose = "ingest" | "discuss" | "verdict" | "summarise";
export type BudgetLevel = "ok" | "warn" | "over";

export interface AnalyticsTotals {
  calls: number;
  failed_calls: number;
  /** Calls whose model had a price; the denominator behind any dollar figure. */
  priced_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
}

export interface AnalyticsLatency {
  median_ms: number | null;
  p95_ms: number | null;
  avg_ms: number | null;
}

export interface ProviderUsage {
  provider: string;
  calls: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
}

export interface ModelUsage {
  provider: string;
  /** Full model id, `<provider>:<name>`, as stored on the review. */
  model: string;
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  avg_latency_ms: number | null;
  findings: number;
  accepted: number;
  acceptance_rate: number | null;
  pushed_back: number;
  pushback_rate: number | null;
}

export interface PurposeUsage {
  purpose: LLMPurpose;
  calls: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
}

export interface QualitySummary {
  findings: number;
  accepted: number;
  acceptance_rate: number | null;
  pushed_back: number;
  pushback_rate: number | null;
}

export interface BudgetStatus {
  month: string;
  token_budget: number | null;
  dollar_budget: number | null;
  tokens_used: number;
  dollars_used: number | null;
  token_pct: number | null;
  dollar_pct: number | null;
  level: BudgetLevel;
}

export interface AnalyticsResponse {
  window_days: number;
  generated_at: string | null;
  totals: AnalyticsTotals;
  latency: AnalyticsLatency;
  by_provider: ProviderUsage[];
  by_model: ModelUsage[];
  by_purpose: PurposeUsage[];
  quality: QualitySummary;
  budget: BudgetStatus;
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
  /** Set on a delta review: the review it continues. */
  parent_review_id: number | null;
  /** `watch` for a review a watch started; `null` when the operator started it. */
  trigger: string | null;
  /** Present on detail responses; `null` in the list. */
  usage: ReviewUsage | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CachedPR {
  id: number;
  pr_url: string;
  repo_owner: string;
  repo_name: string;
  pr_number: number;
  title: string;
  author_username: string;
  author_avatar_url: string | null;
  status: InboxStatus;
  involvement: CachedPRInvolvement;
  has_unread_replies: boolean;
  unread_replies_count: number;
  last_user_action_at: string | null;
  last_github_activity_at: string | null;
  linked_review_id: number | null;
  last_synced_at: string | null;
}

export interface InboxSyncResponse {
  items: CachedPR[];
  disappeared: number;
  warnings: string[];
}

export interface InboxFilters {
  status?: InboxStatus;
  repo?: string;
  unread?: boolean;
}

export interface ReviewWatch {
  id: number;
  pr_url: string;
  vcs: string;
  repo_full_name: string | null;
  pr_number: number | null;
  skill_foundation: string | null;
  model_used: string | null;
  last_seen_commit_id: string | null;
  last_review_id: number | null;
  enabled: boolean;
  last_checked_at: string | null;
  last_error: string | null;
  created_at: string | null;
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
  /** The watch covering this pull request, when there is one. */
  watch: ReviewWatch | null;
  threads: ReviewThread[];
  warnings: string[];
}
