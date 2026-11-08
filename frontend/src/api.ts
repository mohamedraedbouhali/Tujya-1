// Typed client for the FastAPI backend. Every call goes to /api on the same origin; the
// session lives in an HttpOnly cookie, so there is no token to store or attach here.

import { messages } from "./i18n";

export type Role = "admin" | "user";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  phone: string | null;
  /** Profile photo (JPEG); null when the account has none. */
  photo_url: string | null;
  /** Signature (PNG, may be transparent); null when the account has none. */
  signature_url: string | null;
}

/** Only the fields sent change. A new email needs `current_password`. "" removes the phone. */
export interface ProfileChanges {
  full_name?: string;
  email?: string;
  phone?: string;
  current_password?: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminStats {
  users_total: number;
  users_active: number;
  users_inactive: number;
  admins: number;
  signups_last_7_days: number;
  active_sessions: number;
}

/** What an activity event records (backend app/models.py, Action). */
export type ActivityAction =
  | "sign_up"
  | "sign_in"
  | "sign_in_failed"
  | "sign_in_blocked"
  | "sign_out"
  | "scan"
  | "interactions"
  | "chat"
  | "toxicity"
  | "profile_update"
  | "photo_update"
  | "photo_delete"
  | "signature_update"
  | "signature_delete"
  | "password_change"
  | "user_create"
  | "user_update"
  | "password_reset"
  | "user_delete"
  | "report_create"
  | "report_share"
  | "report_unshare"
  | "report_delete"
  | "data_export";

export interface ActivityEvent {
  id: number;
  created_at: string;
  action: ActivityAction;
  user: Pick<User, "id" | "full_name" | "email" | "role" | "is_active" | "photo_url">;
  /** The account an administrator acted on. */
  target_id: number | null;
  /**
   * Counts (pills, items, molecules), changed fields, or for administrator actions the
   * target's name and email as they were. Never a medicine name or a question.
   */
  details: {
    pills?: number;
    items?: number;
    molecules?: number;
    fields?: string[];
    name?: string;
    email?: string;
    role?: Role;
    active?: boolean;
    changes?: { name?: boolean; email?: boolean; role?: Role; active?: boolean };
    /** Reports: how many chat answers it holds, or how many days a link works. */
    answers?: number;
    days?: number;
    /** Exports: which table, how many rows. */
    table?: "users" | "activity";
    rows?: number;
  };
  ip: string | null;
  user_agent: string | null;
}

export interface ActivityPage extends Page<ActivityEvent> {
  /** Events per action for the same account, search and period, whatever the action filter. */
  counts: Partial<Record<ActivityAction, number>>;
}

export interface ActivityFilters {
  user_id?: number;
  action?: ActivityAction[];
  q?: string;
  days?: number;
  page?: number;
  page_size?: number;
}

export interface CatalogSummary {
  drugs: number | null;
  cell_lines: number | null;
  synergy_measurements: number | null;
  abstracts: number | null;
}

export interface Drug {
  drug_id: string;
  name: string;
  synonyms: string[];
  pubchem_cid: number | null;
  chembl_id: string | null;
  smiles: string | null;
  sources: string[];
  n_measurements: number;
}

export interface CellLine {
  cell_line_id: string;
  name: string;
  tissue: string | null;
  disease: string | null;
  depmap_id: string | null;
  sources: string[];
  n_measurements: number;
}

export interface UserFilters {
  q?: string;
  role?: Role | "";
  status?: "active" | "inactive" | "";
  page?: number;
  page_size?: number;
}

export interface NewUser {
  email: string;
  full_name: string;
  password: string;
  role: Role;
  is_active: boolean;
}

export type UserChanges = Partial<Pick<User, "email" | "full_name" | "role" | "is_active">>;

// --- Tujya: scan, pills, interactions (docs/API.md) ------------------------------------------

export interface Source {
  name: string;
  title: string;
  url: string;
  license: string;
  citation: string;
}

export interface PillCandidate {
  class_id: number;
  name: string;
  generic_name: string;
  active_ingredients: string[];
  probability: number;
}

export interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface ScannedPill {
  box: Box;
  box_normalized: Box;
  detection_confidence: number;
  candidates: PillCandidate[];
  needs_confirmation: boolean;
}

export interface ScanResult {
  image_width: number;
  image_height: number;
  inference_ms: number;
  timings: { detection_ms: number; classification_ms: number; total_ms: number };
  confirm_threshold: number;
  pills: ScannedPill[];
  message: string | null;
  models: Record<string, { registered_model?: string; version?: number } | string>;
  sources: Source[];
  disclaimer: string;
}

export interface Pill {
  class_id: number;
  name: string;
  generic_name: string;
  labeled_by: string;
  imprint: string;
  color: string;
  shape: string;
  active_ingredients: string[];
}

export interface PillList {
  items: Pill[];
  total: number;
  sources: Source[];
}

export type Severity = "Major" | "Moderate" | "Minor" | "Unknown";

export interface CheckedItem {
  kind: "pill" | "ingredient";
  label: string;
  class_id: number | null;
  found: boolean;
  active_ingredients: string[];
}

export interface InteractionFound {
  ingredient_a: string;
  ingredient_b: string;
  severity: Severity;
  description: string;
  source: Source;
}

export interface InteractionPair {
  item_a: CheckedItem;
  item_b: CheckedItem;
  highest_severity: Severity | null;
  interactions: InteractionFound[];
  shared_ingredients: string[];
  message: string | null;
}

export interface InteractionsResult {
  items: CheckedItem[];
  pairs: InteractionPair[];
  highest_severity: Severity | null;
  message: string;
  sources: Source[];
  disclaimer: string;
}

export interface DemoImage {
  id: number;
  class_id: number;
  expected_name: string;
  why: string;
  url: string;
  thumbnail_url: string;
}

export interface DemoGallery {
  items: DemoImage[];
  note: string;
}

export interface ChatCitation {
  n: number;
  title: string;
  url: string;
  section: string;
  snippet: string;
  source_name: string;
  doc_type: "label" | "abstract" | "interaction" | string;
  date: string;
  cited: boolean;
}

export interface ChatToolCall {
  name: string;
  args: Record<string, unknown>;
  chosen_by: "llm" | "rule" | string;
  ok: boolean;
  summary: string;
  /** 1, then 2+ when the agent judged the evidence weak and searched again. */
  round?: number;
}

/** How the agent worked: who planned, how many retrieval rounds, the evidence check. */
export interface ChatAgentReport {
  planner?: string;
  rounds?: number;
  refined?: boolean;
  evidence?: { enough?: boolean; missing?: string[]; best_similarity?: number | null };
  cache?: boolean;
  /**
   * "documents": the cited answer. "small_talk" (a greeting) and "general" (a question that
   * is not about medicines) are answered from the model's general knowledge, without sources.
   */
  route?: "documents" | "small_talk" | "general";
}

export interface ChatResult {
  question: string;
  answer: string;
  language: string;
  ingredients: string[];
  citations: ChatCitation[];
  tool_calls: ChatToolCall[];
  safety: { action?: "ok" | "rewritten" | "refused"; violations?: string[]; cited?: number[] };
  agent?: ChatAgentReport;
  model: string;
  timings: Record<string, number>;
  disclaimer: string;
  /** The server's seal: lets this answer go in a report, unchanged (D83). */
  signature: string;
}

/** One Server-Sent Event of POST /api/chat with `stream: true`. */
export type ChatEvent =
  | { type: "tool"; tool: ChatToolCall }
  | { type: "token"; text: string }
  | { type: "final"; result: ChatResult }
  | { type: "error"; detail: string };

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Bonus toxicity tool (POST /api/toxicity, docs/TOXICITY.md): each molecule on its own.
export interface ToxPrediction {
  task: string;
  assay: string;
  probability: number;
  test_roc_auc: number | null;
}

export interface ToxMolecule {
  query: string;
  resolved_as: "ingredient" | "smiles";
  ingredient: string | null;
  smiles: string;
  predictions: ToxPrediction[];
  max_similarity_to_training: number;
  in_domain: boolean;
}

export interface ToxicityResult {
  wording: string;
  molecules: ToxMolecule[];
  errors: { query: string; error: string }[];
  mixture_note: string;
  low_probability_note: string;
  model: { name: string; version: string; tasks: number };
  source: { title: string; url: string; citation: string };
  disclaimer: string;
}

// --- my medicines and reports (D83) ----------------------------------------------------------

export interface SavedPill {
  class_id: number;
  name: string;
  generic_name: string;
  active_ingredients: string[];
  /** The model's probability when confirmed from a scan; null when picked by search. */
  probability: number | null;
  added_at: string;
}

export interface SavedPillList {
  items: SavedPill[];
  sources: Source[];
}

export interface CitationRef {
  n: number;
  title: string;
  url: string;
}

export interface ChatExcerpt {
  question: string;
  answer: string;
  citations: CitationRef[];
}

export interface ReportPill {
  class_id: number;
  name: string;
  generic_name: string;
  active_ingredients: string[];
}

export interface ShareState {
  /** False once the link has expired or was stopped. */
  active: boolean;
  expires_at: string | null;
  views: number;
}

/** What a report says: the same for its owner and for whoever has its link. */
export interface ReportBody {
  id: number;
  created_at: string;
  title: string;
  pills: ReportPill[];
  interactions: InteractionsResult | null;
  chat: ChatExcerpt[];
  highest_severity: Severity | null;
  author: string;
  /** The author's signature as a data: URL, null when none. */
  signature: string | null;
  disclaimer: string;
}

export interface Report extends ReportBody {
  share: ShareState | null;
}

export interface SharedReport extends ReportBody {
  expires_at: string;
}

export interface ReportSummary {
  id: number;
  created_at: string;
  title: string;
  pill_names: string[];
  /** Active ingredients of the pills, each once, sorted: the default title. */
  ingredients: string[];
  highest_severity: Severity | null;
  pairs_with_interaction: number;
  chat_answers: number;
  share: ShareState | null;
}

export interface NewReport {
  title?: string;
  pills: number[];
  chat: (ChatExcerpt & { signature: string })[];
}

export interface UsageDay {
  date: string;
  counts: Partial<Record<ActivityAction, number>>;
  active_users: number;
}

export interface UsageReport {
  days: UsageDay[];
  totals: Partial<Record<ActivityAction, number>>;
  active_users: number;
  new_accounts: number;
  reports_saved: number;
  shared_now: number;
}

/** A chat answer as a report holds it: the question, the answer and its cited sources. */
export function excerptOf(result: ChatResult): ChatExcerpt & { signature: string } {
  return {
    question: result.question,
    answer: result.answer,
    citations: result.citations
      .filter((c) => c.cited)
      .map((c) => ({ n: c.n, title: c.title, url: c.url })),
    signature: result.signature,
  };
}

/** Query string of the activity filters, for links such as the CSV export. */
export function activityQuery(filters: ActivityFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (Array.isArray(value)) value.forEach((item) => params.append(key, String(item)));
    else if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : messages().errors.generic;
}

// Called when a request made as a signed-in user comes back 401: the session has ended.
let onSessionEnded: (() => void) | null = null;

export function setSessionEndedHandler(handler: (() => void) | null): void {
  onSessionEnded = handler;
}

type QueryParams = Record<string, string | number | string[] | undefined>;

interface RequestOptions {
  body?: unknown;
  /** Multipart body (file upload); the browser sets its Content-Type and boundary. */
  form?: FormData;
  query?: QueryParams;
  signal?: AbortSignal;
  /** A 401 is an expected answer here (sign-in form, first load), not a lost session. */
  anonymous?: boolean;
}

/**
 * Turn a FastAPI error body into one readable sentence. The server writes its own messages
 * in English; only the field names and the fallbacks follow the interface language.
 */
function describeFailure(status: number, data: unknown): string {
  const texts = messages();
  const fieldLabels: Record<string, string> = texts.fields;
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((issue: { loc?: unknown[]; msg?: string }) => {
        const field = String(issue.loc?.at(-1) ?? "");
        const message = (issue.msg ?? texts.errors.invalid).replace(/^Value error, /, "");
        return `${fieldLabels[field] ?? field}: ${message}`;
      })
      .join(" ");
  }
  if (status >= 500) return texts.errors.serverDown;
  return texts.errors.requestFailed(status);
}

async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
  const url = new URL(`/api${path}`, window.location.origin);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (Array.isArray(value)) value.forEach((item) => url.searchParams.append(key, item));
    else if (value !== undefined && value !== "") url.searchParams.set(key, String(value));
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
      signal: options.signal,
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    throw new ApiError(0, messages().errors.unreachable);
  }

  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !options.anonymous) onSessionEnded?.();
    throw new ApiError(response.status, describeFailure(response.status, data));
  }
  return data as T;
}

/**
 * Ask the Tujya agent; the answer streams as Server-Sent Events (tool calls, then the
 * checked sentences, then the final result, which is the one to display).
 */
async function chatStream(
  question: string,
  pills: number[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(new URL("/api/chat", window.location.origin), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({ question, pills, stream: true }),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(0, messages().errors.unreachable);
  }
  if (!response.ok || !response.body) {
    const data: unknown = await response.json().catch(() => null);
    if (response.status === 401) onSessionEnded?.();
    throw new ApiError(response.status, describeFailure(response.status, data));
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end = buffer.indexOf("\n\n");
    while (end !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const name = /^event: (.+)$/m.exec(block)?.[1];
      const data = /^data: (.+)$/m.exec(block)?.[1];
      if (name && data) {
        const payload = JSON.parse(data);
        if (name === "final") onEvent({ type: "final", result: payload as ChatResult });
        else if (name === "tool") onEvent({ type: "tool", tool: payload.tool });
        else if (name === "token") onEvent({ type: "token", text: payload.text });
        else if (name === "error") onEvent({ type: "error", detail: payload.detail });
      }
      end = buffer.indexOf("\n\n");
    }
  }
}

export const api = {
  me: () => request<User>("GET", "/auth/me", { anonymous: true }),
  signIn: (email: string, password: string) =>
    request<User>("POST", "/auth/login", { body: { email, password }, anonymous: true }),
  signUp: (account: { email: string; full_name: string; password: string }) =>
    request<User>("POST", "/auth/signup", { body: account, anonymous: true }),
  signOut: () => request<void>("POST", "/auth/logout", { anonymous: true }),
  updateProfile: (changes: ProfileChanges) =>
    request<User>("PATCH", "/auth/me", { body: changes }),
  uploadPhoto: (image: Blob) => {
    const form = new FormData();
    form.append("image", image, "photo.jpg");
    return request<User>("PUT", "/auth/me/photo", { form });
  },
  deletePhoto: () => request<User>("DELETE", "/auth/me/photo"),
  uploadSignature: (image: Blob) => {
    const form = new FormData();
    form.append("image", image, "signature.png");
    return request<User>("PUT", "/auth/me/signature", { form });
  },
  deleteSignature: () => request<User>("DELETE", "/auth/me/signature"),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("POST", "/auth/me/password", { body: { current_password, new_password } }),

  // Public: the introduction page shows these counts before anyone has signed in.
  catalogSummary: (signal?: AbortSignal) =>
    request<CatalogSummary>("GET", "/public/summary", { signal, anonymous: true }),
  drugs: (query: QueryParams, signal?: AbortSignal) =>
    request<Page<Drug>>("GET", "/catalog/drugs", { query, signal }),
  cellLines: (query: QueryParams, signal?: AbortSignal) =>
    request<Page<CellLine>>("GET", "/catalog/cell-lines", { query, signal }),

  /** `live`: a webcam preview frame, which the server leaves out of the activity log. */
  scan: (image: Blob, filename: string, signal?: AbortSignal, live = false) => {
    const form = new FormData();
    form.append("image", image, filename);
    const query = live ? { live: "true" } : undefined;
    return request<ScanResult>("POST", "/scan", { form, signal, query });
  },
  pills: (q: string, signal?: AbortSignal) =>
    request<PillList>("GET", "/pills", { query: { q, limit: 12 }, signal }),
  interactions: (pills: number[], ingredients: string[] = []) =>
    request<InteractionsResult>("POST", "/interactions", { body: { pills, ingredients } }),
  demoImages: (signal?: AbortSignal) => request<DemoGallery>("GET", "/demo/images", { signal }),
  toxicity: (molecules: string[]) =>
    request<ToxicityResult>("POST", "/toxicity", { body: { molecules } }),
  chat: (question: string, pills: number[]) =>
    request<ChatResult>("POST", "/chat", { body: { question, pills, stream: false } }),
  chatStream,
  /** A demo photo as a file, to send it to the scan like an upload. */
  demoImage: async (image: DemoImage): Promise<Blob> => {
    const response = await fetch(image.url, { credentials: "same-origin" });
    if (!response.ok) throw new ApiError(response.status, messages().errors.demoPhoto);
    return response.blob();
  },

  admin: {
    stats: (signal?: AbortSignal) => request<AdminStats>("GET", "/admin/stats", { signal }),
    users: (filters: UserFilters, signal?: AbortSignal) =>
      request<Page<User>>("GET", "/admin/users", { query: { ...filters }, signal }),
    createUser: (account: NewUser) => request<User>("POST", "/admin/users", { body: account }),
    updateUser: (id: number, changes: UserChanges) =>
      request<User>("PATCH", `/admin/users/${id}`, { body: changes }),
    resetPassword: (id: number, new_password: string) =>
      request<void>("POST", `/admin/users/${id}/password`, { body: { new_password } }),
    deleteUser: (id: number) => request<void>("DELETE", `/admin/users/${id}`),
    user: (id: number, signal?: AbortSignal) =>
      request<User>("GET", `/admin/users/${id}`, { signal }),
    activity: (filters: ActivityFilters, signal?: AbortSignal) =>
      request<ActivityPage>("GET", "/admin/activity", { query: { ...filters }, signal }),
    /** `tz`: minutes to add to UTC, so the days are the administrator's own. */
    usage: (days: number, signal?: AbortSignal) =>
      request<UsageReport>("GET", "/admin/usage", {
        query: { days, tz: -new Date().getTimezoneOffset() },
        signal,
      }),
    /** Plain links: the browser downloads them with the session cookie. */
    usersCsvUrl: "/api/admin/export/users.csv",
    activityCsvUrl: (filters: ActivityFilters) =>
      `/api/admin/export/activity.csv${activityQuery(filters)}`,
  },

  my: {
    medicines: (signal?: AbortSignal) =>
      request<SavedPillList>("GET", "/my/medicines", { signal }),
    addMedicine: (class_id: number, probability: number | null) =>
      request<SavedPillList>("POST", "/my/medicines", { body: { class_id, probability } }),
    removeMedicine: (class_id: number) =>
      request<SavedPillList>("DELETE", `/my/medicines/${class_id}`),
    clearMedicines: () => request<void>("DELETE", "/my/medicines"),
    reports: (page: number, signal?: AbortSignal) =>
      request<Page<ReportSummary>>("GET", "/my/reports", { query: { page }, signal }),
    report: (id: number, signal?: AbortSignal) =>
      request<Report>("GET", `/my/reports/${id}`, { signal }),
    createReport: (report: NewReport) => request<Report>("POST", "/my/reports", { body: report }),
    deleteReport: (id: number) => request<void>("DELETE", `/my/reports/${id}`),
    share: (id: number, days: number) =>
      request<{ token: string; expires_at: string }>("POST", `/my/reports/${id}/share`, {
        body: { days },
      }),
    stopSharing: (id: number) => request<void>("DELETE", `/my/reports/${id}/share`),
  },

  /** A shared report, read only, without signing in. */
  shared: (token: string, signal?: AbortSignal) =>
    request<SharedReport>("POST", "/shared", { body: { token }, signal, anonymous: true }),
};
