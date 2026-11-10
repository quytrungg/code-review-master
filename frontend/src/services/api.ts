import type {
  AnalyticsResponse,
  AppSettings,
  ApplyResponse,
  AuthUser,
  CodeReviewDetail,
  CodeReviewSummary,
  ConnectionTestResponse,
  CreateReviewAccepted,
  DiscussResponse,
  Foundation,
  LLMKey,
  LLMKeyCreate,
  KeyTestResult,
  ModelCatalog,
  ReviewVerdict,
  RoundDecision,
  RoundDecisionResponse,
  SettingsUpdate,
  SyncResponse,
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

  discuss: (reviewId: number, threads: { thread_id: number; message: string }[]) =>
    request<DiscussResponse>(`/reviews/${reviewId}/discuss`, {
      method: "POST",
      body: JSON.stringify({ threads }),
    }),

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
};
