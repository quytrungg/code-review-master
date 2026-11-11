import type {
  AnalyticsResponse,
  AppSettings,
  ApplyResponse,
  AuthUser,
  CachedPR,
  CodeReviewDetail,
  CodeReviewSummary,
  ConnectionTestResponse,
  CreateReviewAccepted,
  DiscussionStreamEvent,
  Foundation,
  InboxFilters,
  InboxSyncResponse,
  LLMKey,
  LLMKeyCreate,
  KeyTestResult,
  LessonApplyResult,
  LessonDraft,
  ModelCatalog,
  QuickReviewEvent,
  ReviewVerdict,
  ReviewWatch,
  RoundDecision,
  RoundDecisionResponse,
  SettingsUpdate,
  SyncResponse,
  SkillEvolutionAnalysis,
  SkillEvolutionApplyResponse,
  SkillEvolutionCloneResponse,
  SkillEvolutionFileChange,
  SkillFileUpload,
  SkillsResponse,
  VersionControlKey,
  VersionControlKeyCreate,
} from "@/types";

const BASE_URL = "/api";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const headers: HeadersInit = isFormData
    ? { ...(init?.headers ?? {}) }
    : { "Content-Type": "application/json", ...(init?.headers ?? {}) };

  let response: Response;
  try {
    // Same-origin keeps the HttpOnly session cookie on every call.
    response = await fetch(`${BASE_URL}${path}`, {
      credentials: "same-origin",
      ...init,
      headers,
    });
  } catch {
    throw new ApiError("Cannot reach the API. Is the backend running on :8000?", 0);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  // Accounts: the cookie is the session; no token is ever stored in JS.
  me: () => request<AuthUser>("/auth/me"),
  signup: (email: string, password: string) =>
    request<AuthUser>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<AuthUser>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),

  getSettings: (reveal = false) => request<AppSettings>(`/settings${reveal ? "?reveal=true" : ""}`),

  updateSettings: (payload: SettingsUpdate) =>
    request<AppSettings>("/settings", { method: "PUT", body: JSON.stringify(payload) }),

  // Beta flags: full-dict replace, so the toggle sends every registry id at once.
  setBetaFeatures: (flags: Record<string, boolean>) =>
    request<AppSettings>("/settings", {
      method: "PUT",
      body: JSON.stringify({ beta_features: flags }),
    }),

  testConnection: (targets: string[]) =>
    request<ConnectionTestResponse>("/settings/test-connection", {
      method: "POST",
      body: JSON.stringify({ targets }),
    }),

  // Credentials: one list per family, referenced by settings.
  listVersionControlKeys: (reveal = false) =>
    request<VersionControlKey[]>(`/keys/version-control${reveal ? "?reveal=true" : ""}`),

  createVersionControlKey: (payload: VersionControlKeyCreate) =>
    request<VersionControlKey>("/keys/version-control", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  updateVersionControlKey: (id: number, payload: Partial<VersionControlKeyCreate>) =>
    request<VersionControlKey>(`/keys/version-control/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  deleteVersionControlKey: (id: number) =>
    request<void>(`/keys/version-control/${id}`, { method: "DELETE" }),

  testVersionControlKey: (id: number) =>
    request<KeyTestResult>(`/keys/version-control/${id}/test`, { method: "POST" }),

  listLLMKeys: (reveal = false) =>
    request<LLMKey[]>(`/keys/llm${reveal ? "?reveal=true" : ""}`),

  createLLMKey: (payload: LLMKeyCreate) =>
    request<LLMKey>("/keys/llm", { method: "POST", body: JSON.stringify(payload) }),

  updateLLMKey: (id: number, payload: Partial<LLMKeyCreate>) =>
    request<LLMKey>(`/keys/llm/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),

  deleteLLMKey: (id: number) => request<void>(`/keys/llm/${id}`, { method: "DELETE" }),

  testLLMKey: (id: number) =>
    request<KeyTestResult>(`/keys/llm/${id}/test`, { method: "POST" }),

  listReviews: () => request<CodeReviewSummary[]>("/reviews"),

  createReview: (prUrl: string, model: string, skillFoundation?: string) =>
    request<CreateReviewAccepted>("/reviews", {
      method: "POST",
      body: JSON.stringify({
        pr_url: prUrl,
        model,
        skill_foundation: skillFoundation || null,
      }),
    }),

  eventsUrl: (reviewId: number) => `${BASE_URL}/reviews/${reviewId}/events`,

  getReview: (id: number) => request<CodeReviewDetail>(`/reviews/${id}`),

  /**
   * The streaming discussion endpoint. `fetch` (not the JSON client) because the body is a
   * Server-Sent Events stream; `signal` aborts it, which is how the Stop button cancels.
   * Pre-stream failures (404/400/422) throw an ApiError with the same shape as `request`.
   * The JSON variant stayed for API compatibility and tests, but the workspace only streams.
   */
  streamDiscussion: async (
    reviewId: number,
    threads: { thread_id: number; message: string }[],
    onEvent: (event: DiscussionStreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> => {
    let response: Response;
    try {
      response = await fetch(`${BASE_URL}/reviews/${reviewId}/discuss/stream`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threads }),
        signal,
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      throw new ApiError("Cannot reach the API. Is the backend running on :8000?", 0);
    }

    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body?.detail === "string") detail = body.detail;
        else if (Array.isArray(body?.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(detail, response.status);
    }
    if (!response.body) {
      throw new ApiError("The browser could not open the discussion stream.", 0);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        let name: string | null = null;
        let data: string | null = null;
        for (const line of block.split("\n")) {
          if (line.startsWith("event: ")) name = line.slice(7);
          else if (line.startsWith("data: ")) data = line.slice(6);
        }
        if (name && data) {
          onEvent({ type: name, ...JSON.parse(data) } as DiscussionStreamEvent);
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  },

  applyReview: (reviewId: number, payload: { event: ReviewVerdict; thread_ids?: number[] }) =>
    request<ApplyResponse>(`/reviews/${reviewId}/apply`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  syncReview: (reviewId: number) =>
    request<SyncResponse>(`/reviews/${reviewId}/sync`, { method: "POST" }),

  decideRound: (reviewId: number, roundId: number, decision: RoundDecision, summary?: string) =>
    request<RoundDecisionResponse>(`/reviews/${reviewId}/rounds/${roundId}/decision`, {
      method: "POST",
      body: JSON.stringify({ decision, summary: summary ?? null }),
    }),

  draftLesson: (reviewId: number, threadId: number) =>
    request<LessonDraft>(`/reviews/${reviewId}/threads/${threadId}/lesson/draft`, {
      method: "POST",
    }),

  applyLesson: (
    reviewId: number,
    threadId: number,
    payload: { foundation_id: string; title: string; body: string },
  ) =>
    request<LessonApplyResult>(`/reviews/${reviewId}/threads/${threadId}/lesson`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listInbox: (filters: InboxFilters = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.repo) params.set("repo", filters.repo);
    if (filters.unread) params.set("unread", "true");
    const suffix = params.size ? `?${params.toString()}` : "";
    return request<CachedPR[]>(`/inbox${suffix}`);
  },

  syncInbox: () => request<InboxSyncResponse>("/inbox/sync", { method: "POST" }),

  quickReview: (cachedPrId: number, event: QuickReviewEvent, body?: string) =>
    request<CachedPR>("/inbox/quick-review", {
      method: "POST",
      body: JSON.stringify({ cached_pr_id: cachedPrId, event, body: body ?? null }),
    }),

  polishComment: (text: string) =>
    request<{ text: string }>("/inbox/polish", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  listWatches: () => request<ReviewWatch[]>("/watches"),

  createWatch: (reviewId: number) =>
    request<ReviewWatch>("/watches", { method: "POST", body: JSON.stringify({ review_id: reviewId }) }),

  updateWatch: (watchId: number, enabled: boolean) =>
    request<ReviewWatch>(`/watches/${watchId}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),

  deleteWatch: (watchId: number) => request<void>(`/watches/${watchId}`, { method: "DELETE" }),

  getAnalytics: (days = 30) => request<AnalyticsResponse>(`/analytics?days=${days}`),

  listModels: () => request<ModelCatalog>("/models"),

  listSkills: () => request<SkillsResponse>("/skills"),

  uploadSkillFile: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<SkillFileUpload>("/skills/files", { method: "POST", body });
  },

  createFoundation: (name: string, files?: File[], archive?: File) => {
    const body = new FormData();
    body.append("name", name);
    for (const file of files ?? []) {
      // Browsers keep the relative path when a filename is supplied for the part.
      const relative = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
      body.append("files", file, relative);
    }
    if (archive) body.append("archive", archive, archive.name);
    return request<Foundation>("/skills/foundations", { method: "POST", body });
  },

  deleteFoundation: (id: string) =>
    request<void>(`/skills/foundations/${encodeURIComponent(id)}`, { method: "DELETE" }),

  // Skill evolution: propose guideline edits from the recent review history, then apply them.
  analyzeSkillHistory: (foundationId: string, days: number, model: string) =>
    request<SkillEvolutionAnalysis>(`/skills/${encodeURIComponent(foundationId)}/analyze-history`, {
      method: "POST",
      body: JSON.stringify({ days, model }),
    }),

  applySkillEvolution: (foundationId: string, files: SkillEvolutionFileChange[]) =>
    request<SkillEvolutionApplyResponse>(`/skills/${encodeURIComponent(foundationId)}/apply`, {
      method: "POST",
      body: JSON.stringify({ files }),
    }),

  cloneSkillEvolution: (
    foundationId: string,
    newFoundationName: string,
    files: SkillEvolutionFileChange[],
  ) =>
    request<SkillEvolutionCloneResponse>(
      `/skills/${encodeURIComponent(foundationId)}/clone-and-apply`,
      {
        method: "POST",
        body: JSON.stringify({ new_foundation_name: newFoundationName, files }),
      },
    ),
};
