// API client — calls FastAPI directly, no BFF proxy.
// JWT is stored client-side and sent per-request.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

const REQUEST_TIMEOUT_MS = 20000;

interface RequestOptions extends RequestInit {
  token?: string;
}

/** Read an error body that may not be JSON (proxy HTML 502/504, etc.). */
async function errorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const text = await response.text();
    if (!text) return fallback;
    try {
      const parsed = JSON.parse(text);
      return parsed?.detail || fallback;
    } catch {
      return text.length > 200 ? fallback : text;
    }
  } catch {
    return fallback;
  }
}

/**
 * fetch with a timeout + abort. A hung backend must not leave the chat
 * spinner or admin panel loading forever.
 */
async function fetchWithTimeout(path: string, options: RequestOptions = {}): Promise<Response> {
  const { token, ...init } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        ...(init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init.headers ?? {}),
      },
    });
  } finally {
    clearTimeout(timer);
  }
}

/** Standard error body extraction for calls routed through fetchWithTimeout. */
async function throwApiError(response: Response, fallback: string): Promise<never> {
  throw new Error(await errorDetail(response, fallback));
}

export interface HistoryTurn {
  question: string;
  answer?: string;
}

export interface SearchRequest {
  query: string;
  history?: HistoryTurn[];
}

export interface SearchExcerpt {
  text: string;
  source: {
    title: string;
    section: string | null;
    chunk_type: string;
  };
  confidence: number;
}

export interface AnswerBlock {
  question: string;
  title: string;
  answer_phrase: string;
  excerpts: SearchExcerpt[];
  confidence: number;
  routing: 'answer' | 'partial' | 'no_answer';
}

export interface SearchResponse {
  response_id: string;
  answers: AnswerBlock[];
  title: string;
  answer_phrase: string;
  excerpts: SearchExcerpt[];
  confidence: number;
  routing: 'answer' | 'partial' | 'no_answer';
  related_questions: string[];
  answered: number;
  total: number;
  comparison: boolean;
}

export interface AuthLoginRequest {
  email: string;
  password: string;
}

export interface AuthLoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export async function searchKnowledgeBase(
  query: string,
  token?: string,
  history?: HistoryTurn[]
): Promise<SearchResponse> {
  const body: SearchRequest = history && history.length > 0 ? { query, history } : { query };

  const response = await fetchWithTimeout(`/search/`, {
    method: 'POST',
    token,
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    await throwApiError(response, 'Search request failed');
  }

  return response.json();
}

export async function login(
  email: string,
  password: string
): Promise<AuthLoginResponse> {
  const response = await fetchWithTimeout(`/auth/login`, {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    await throwApiError(response, 'Login failed');
  }

  return response.json();
}

export async function verifyToken(
  token: string
): Promise<{ valid: boolean; user_id?: number; email?: string }> {
  const response = await fetchWithTimeout(`/auth/verify`, {
    method: 'POST',
    token,
  });

  if (!response.ok) {
    return { valid: false };
  }

  return response.json();
}

export interface FeedbackRequest {
  response_id: string;
  rating: 1 | -1;
  comment?: string;
}

export interface UserSettings {
  show_related_questions: boolean;
}

export async function getUserSettings(
  token?: string
): Promise<UserSettings> {
  const response = await fetchWithTimeout(`/settings/`, {
    method: 'GET',
    token,
  });

  if (!response.ok) {
    await throwApiError(response, 'Failed to fetch settings');
  }

  return response.json();
}

export async function updateUserSettings(
  settings: UserSettings,
  token?: string
): Promise<UserSettings> {
  const response = await fetchWithTimeout(`/settings/`, {
    method: 'PUT',
    token,
    body: JSON.stringify(settings),
  });

  if (!response.ok) {
    await throwApiError(response, 'Failed to update settings');
  }

  return response.json();
}

export async function submitFeedback(
  request: FeedbackRequest,
  token?: string
): Promise<{ message: string; feedback_id: number }> {
  const response = await fetchWithTimeout(`/feedback/`, {
    method: 'POST',
    token,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    await throwApiError(response, 'Feedback submission failed');
  }

  return response.json();
}

// --- Admin panel ---

export interface AdminUser {
  id: number;
  email: string;
  full_name: string | null;
  role: string;
  department: string;
  allowed_departments: string[];
  client_id: string | null;
  assigned_clients: string[];
  assigned_cases: string[];
  is_active: boolean;
  created_at: string;
}

export interface AdminDocument {
  id: number;
  title: string;
  source_path: string | null;
  doc_type: string;
  department: string;
  is_active: boolean;
  is_approved: boolean;
  client_id: string | null;
  property_id: string | null;
  case_id: string | null;
  version: number;
  /** User id of the contributor; null for documents ingested by batch. */
  uploaded_by: number | null;
  created_at: string;
}

/** One selectable document type or department. */
export interface CategoryOption {
  value: string;
  label: string;
}

/**
 * The category vocabulary, served by the backend rather than duplicated
 * here so that adding a category stays a backend-only change.
 */
export interface DocumentCategories {
  doc_types: CategoryOption[];
  departments: CategoryOption[];
  auto_doc_type: string;
  default_department: string;
}

export interface AuditEntry {
  id: number;
  email: string | null;
  query: string;
  sub_queries?: unknown;
  confidence: number | null;
  outcome: string | null;
  latency_ms: number | null;
  created_at: string;
}

export interface FeedbackEntry {
  id: number;
  email: string | null;
  rating: number;
  comment: string | null;
  response_id: string;
  created_at: string;
}

export interface KnowledgeGap {
  id: number;
  query: string;
  intent: string | null;
  confidence: number | null;
  acknowledged: boolean;
  acknowledged_at: string | null;
  acknowledged_by_email: string | null;
  created_at: string;
}

export interface AdminStats {
  users: number;
  active_users: number;
  documents: number;
  active_documents: number;
  chunks: number;
  queries: number;
  no_answer: number;
  avg_confidence: number;
  thumbs_up: number;
  thumbs_down: number;
  knowledge_gaps: number;
  recent_activity: AuditEntry[];
}

async function adminFetch<T>(path: string, token: string, method: string = "GET"): Promise<T> {
  const response = await fetchWithTimeout(path, {
    method,
    token,
  });

  if (!response.ok) {
    await throwApiError(response, 'Admin request failed');
  }

  return response.json();
}

export async function getAdminStats(token: string): Promise<{ stats: AdminStats }> {
  return adminFetch('/admin/stats', token);
}

export async function getAdminUsers(token: string): Promise<{ users: AdminUser[] }> {
  return adminFetch('/admin/users', token);
}

export interface CreateUserRequest {
  email: string;
  password: string;
  full_name?: string | null;
  role: string;
  department: string;
  allowed_departments: string[];
  client_id?: string | null;
  assigned_clients: string[];
  assigned_cases: string[];
}

export async function createUser(
  req: CreateUserRequest,
  token: string
): Promise<{ user: AdminUser }> {
  const response = await fetchWithTimeout(`/admin/users`, {
    method: "POST",
    token,
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    await throwApiError(response, "Failed to create user");
  }

  return response.json();
}

/**
 * Assignable staff roles, lowest privilege first. Served by the backend so
 * a role rename cannot leave the UI offering one the API would reject.
 */
export async function getAdminRoles(
  token: string
): Promise<{ roles: string[] }> {
  return adminFetch('/admin/roles', token);
}

export async function getAdminDocuments(
  token: string
): Promise<{ documents: AdminDocument[] }> {
  return adminFetch('/documents/', token);
}

/**
 * The caller's own uploads, approved or not. Scoped server-side by
 * uploaded_by, so a processor sees nothing they did not submit.
 */
export async function getMyDocuments(
  token: string
): Promise<{ documents: AdminDocument[] }> {
  return adminFetch('/documents/mine', token);
}

export async function getAdminAudit(
  token: string,
  limit = 100
): Promise<{ audit: AuditEntry[] }> {
  return adminFetch(`/admin/audit?limit=${limit}`, token);
}

export async function getAdminFeedback(
  token: string,
  limit = 100
): Promise<{ feedback: FeedbackEntry[] }> {
  return adminFetch(`/admin/feedback?limit=${limit}`, token);
}

export async function getKnowledgeGaps(
  token: string,
  limit = 100
): Promise<{ knowledge_gaps: KnowledgeGap[] }> {
  return adminFetch(`/analytics/knowledge-gaps?limit=${limit}`, token);
}

export async function acknowledgeGap(
  gapId: number,
  token: string
): Promise<{ message: string; gap_id: number }> {
  return adminFetch(`/analytics/knowledge-gaps/${gapId}/acknowledge`, token, "POST");
}

export async function fetchDocumentCategories(
  token: string
): Promise<DocumentCategories> {
  const response = await fetchWithTimeout(`/documents/categories`, { token });
  if (!response.ok) {
    throw new Error("Could not load document categories");
  }
  return response.json();
}

export async function uploadDocument(
  file: File,
  token: string,
  category?: { docType: string; department: string },
  // Optional Intelliflo client reference (Stage 2, Task 5) — independent
  // of category, so it's its own argument rather than folded into
  // `category`, which the caller may omit entirely.
  clientId?: string
): Promise<{
  message: string;
  filename: string;
  stored_as: string;
  size_bytes: number;
  indexing: boolean;
  doc_type: string | null;
  department: string | null;
  client_id: string | null;
}> {
  const form = new FormData();
  form.append("file", file);
  if (category) {
    form.append("doc_type", category.docType);
    form.append("department", category.department);
  }
  if (clientId) {
    form.append("client_id", clientId);
  }
  const response = await fetchWithTimeout(`/documents/upload`, {
    method: "POST",
    token,
    body: form,
  });

  if (!response.ok) {
    await throwApiError(response, "Upload failed");
  }

  return response.json();
}

export async function updateUserAdmin(
  userId: number,
  patch: Partial<AdminUser & { role?: string }>,
  token: string
): Promise<{ user: AdminUser }> {
  const response = await fetchWithTimeout(`/admin/users/${userId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify(patch),
  });

  if (!response.ok) {
    await throwApiError(response, "Update failed");
  }

  return response.json();
}

export async function approveDocument(
  documentId: number,
  token: string
): Promise<{ message: string; document_id: number; title: string; chunks_updated: number }> {
  const response = await fetchWithTimeout(`/documents/${documentId}/approve`, {
    method: "PATCH",
    token,
  });

  if (!response.ok) {
    await throwApiError(response, "Approval failed");
  }

  return response.json();
}
