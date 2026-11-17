export type ReviewStatus = "running" | "draft" | "in_discussion" | "applied" | "failed";
export type ReviewVerdict = "APPROVE" | "REQUEST_CHANGES" | "COMMENT";
export type InboxStatus = "needs_review" | "approved" | "request_changed" | "commented";
export type CachedPRInvolvement = "reviewer" | "assignee" | "author";
export type QuickReviewEvent = ReviewVerdict;
export type MessageRole = "assistant" | "user" | "system";
export type ThreadOrigin = "AI_GENERATED" | "GITHUB_EXISTING" | "CHECK";
export type ThreadStatus = "active" | "needs_response" | "applied" | "resolved";
export type RoundStatus = "drafting" | "pending_apply" | "published" | "resolved_no_reply";

export type VcsProvider = "github" | "gitlab";
export type LLMProvider = "claude" | "openai" | "opencode" | "ollama_cloud" | "ollama_local";

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
  /** `oauth` for a Claude sign-in; its refresh token never leaves the server. */
  auth_type: "api_key" | "oauth";
  has_refresh_token: boolean;
  expires_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  api_key?: string | null;
}

/** The URL for the Claude sign-in page, and when that attempt stops being valid. */
export interface ClaudeOAuthStart {
  authorize_url: string;
  expires_at: string | null;
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
  // Beta flags: one key per registry id, false when off. `beta_registry` is the render source.
  beta_features: Record<string, boolean>;
  beta_registry: BetaFeature[];
  // Deterministic pre-pass packs: the selected ids and every pack to render.
  check_packs: string[];
  check_pack_registry: CheckPack[];
  updated_at: string | null;
  version_control_token?: string | null;
  llm_api_key?: string | null;
}

export interface SettingsUpdate {
  version_control_key_id?: number | null;
  llm_key_id?: number | null;
  monthly_token_budget?: number | null;
  monthly_dollar_budget?: number | null;
  beta_features?: Record<string, boolean> | null;
  check_packs?: string[] | null;
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
  provider: "claude" | "openai" | "opencode" | "ollama-cloud" | "ollama-local";
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
  /** Local CLI-agent session folders the evolve analysis can read. */
  session_sources: SessionSource[];
}

/** One local CLI-agent store the evolve analysis can mine for corrections. */
export type EvolutionSessionSource = "claude" | "codex" | "hermes";

export interface SessionSource {
  id: EvolutionSessionSource;
  label: string;
  path: string;
  available: boolean;
  detail?: string | null;
}

export interface SkillFileUpload {
  path: string;
  foundation: string;
  bytes: number;
}

/** What the meta-analysis proposes for one rule file. */
export type SkillEvolutionAction = "modify" | "create" | "delete";

export interface SkillFileModification {
  file_path: string;
  action: SkillEvolutionAction;
  rationale: string;
  evidence_review_ids: number[];
  original_content: string;
  proposed_content: string;
  unified_diff: string;
}

export interface SkillEvolutionHistory {
  days: number;
  reviews: number;
  threads: number;
  interactions: number;
  /** Set when a local agent session store was added to the analysis. */
  session_source: EvolutionSessionSource | null;
  sessions: number;
  exchanges: number;
}

export interface SkillEvolutionAnalysis {
  analysis_summary: string;
  file_modifications: SkillFileModification[];
  history: SkillEvolutionHistory;
  warnings: string[];
}

/** One approved edit: the operator's final text, after any in-browser edit. */
export interface SkillEvolutionFileChange {
  file_path: string;
  action: SkillEvolutionAction;
  content: string;
}

export interface SkillEvolutionApplyResponse {
  foundation: string;
  applied: string[];
  backup_path: string | null;
  warnings: string[];
}

export interface SkillEvolutionCloneResponse {
  foundation: Foundation;
  applied: string[];
  warnings: string[];
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

export type LLMPurpose = "ingest" | "discuss" | "verdict" | "summarise" | "polish" | "evolve" | "lesson";
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
  /** Keys seen in more than one review in the window. */
  recurring: RecurringFinding[];
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
  /** A finished review nobody has opened yet: the row shows a dot and the navbar counts it. */
  has_unread: boolean;
  /** Present on detail responses; `null` in the list. */
  usage: ReviewUsage | null;
  created_at: string | null;
  updated_at: string | null;
}

/** The Reviews badge: finished reviews on this account that have not been opened. */
export interface ReviewNotifications {
  unread_count: number;
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

/** Events from POST /reviews/{id}/discuss/stream; `done` is always last (absent on abort). */
export type DiscussionStreamEvent =
  | { type: "thread_started"; thread_id: number }
  | { type: "delta"; thread_id: number; text: string }
  | { type: "thread_done"; thread_id: number; message_id: number; references: number[] }
  | { type: "thread_error"; thread_id: number; error: string; references: number[] }
  | {
      type: "done";
      answered: number;
      failed: number;
      opinion_refreshed: boolean;
      warnings: string[];
    };

export interface DiscussionDone {
  answered: number;
  failed: number;
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
  /** True once this review approved the pull request; blocks a duplicate approval. */
  approval_published: boolean;
  /** The watch covering this pull request, when there is one. */
  watch: ReviewWatch | null;
  threads: ReviewThread[];
  warnings: string[];
}

/** One reviewer push-back against the AI's opinion, and the model's answer to it. */
export interface VerdictPushback {
  id: number;
  argument: string;
  previous_verdict: ReviewVerdict | null;
  previous_confidence: number | null;
  agrees: boolean;
  verdict: ReviewVerdict;
  confidence: number | null;
  response: string;
  created_at: string | null;
}

export interface VerdictPushbackResponse {
  pushback: VerdictPushback;
  review: CodeReviewDetail;
}

export interface BetaFeature {
  id: string;
  label: string;
  description: string;
}

/** One deterministic pre-pass pack, rendered as a Settings checkbox. */
export interface CheckPack {
  id: string;
  label: string;
  description: string;
}

/** A standing review policy: a repo glob, a model, a foundation and a concurrency cap. */
export interface ReviewPolicy {
  id: number;
  repo_pattern: string;
  involvement: "reviewer" | "assignee" | "author" | "any";
  model_used: string;
  skill_foundation: string | null;
  max_active: number;
  enabled: boolean;
  last_run_at: string | null;
  last_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ReviewPolicyCreate {
  repo_pattern: string;
  involvement: ReviewPolicy["involvement"];
  model: string;
  skill_foundation?: string | null;
  max_active?: number;
  enabled?: boolean;
}

/** One prior finding, from search or the "seen before" panel. */
export interface FindingHit {
  review_id: number;
  thread_id: number;
  repo_full_name: string | null;
  file_path: string;
  line_number: number;
  origin: ThreadOrigin;
  snippet: string;
  accepted: boolean;
  created_at: string | null;
}

export interface FindingSearchResponse {
  items: FindingHit[];
  total: number;
}

export interface SimilarFindingsResponse {
  items: FindingHit[];
}

/** A key seen in more than one review in one repository. Evidence, not a duplicate claim. */
export interface RecurringFinding {
  repo_full_name: string;
  key: string;
  reviews: number;
  findings: number;
  last_seen: string | null;
}

export interface ComparisonSide {
  id: number;
  model_used: string | null;
  thread_count: number;
}

export interface ComparisonMatch {
  primary_thread_id: number;
  comparison_thread_id: number;
  file_path: string;
  primary_line: number;
  comparison_line: number;
  snippet: string;
}

export interface ComparisonItem {
  review_id: number;
  thread_id: number;
  file_path: string;
  line_number: number;
  origin: ThreadOrigin;
  snippet: string;
}

export interface ComparisonRead {
  primary: ComparisonSide;
  comparison: ComparisonSide;
  both: ComparisonMatch[];
  primary_only: ComparisonItem[];
  comparison_only: ComparisonItem[];
  line_tolerance: number;
}

export interface ComparisonEstimate {
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  estimated_cost_usd: number | null;
  note: string;
}

export interface LessonDraft {
  title: string;
  body: string;
}

export interface LessonApplyResult {
  path: string;
  foundation: string;
  lesson_id: number;
}
