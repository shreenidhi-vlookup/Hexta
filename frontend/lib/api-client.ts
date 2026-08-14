// API client — calls FastAPI directly, no BFF proxy.
// JWT is stored client-side and sent per-request.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

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
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const body: SearchRequest = history && history.length > 0 ? { query, history } : { query };

  const response = await fetch(`${API_BASE_URL}/search/`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Search request failed');
  }

  return response.json();
}

export async function login(
  email: string,
  password: string
): Promise<AuthLoginResponse> {
  const response = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Login failed');
  }

  return response.json();
}

export async function verifyToken(
  token: string
): Promise<{ valid: boolean; user_id?: number; email?: string }> {
  const response = await fetch(`${API_BASE_URL}/auth/verify`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
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
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/settings/`, {
    method: 'GET',
    headers,
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to fetch settings');
  }

  return response.json();
}

export async function updateUserSettings(
  settings: UserSettings,
  token?: string
): Promise<UserSettings> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/settings/`, {
    method: 'PUT',
    headers,
    body: JSON.stringify(settings),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Failed to update settings');
  }

  return response.json();
}

export async function submitFeedback(
  request: FeedbackRequest,
  token?: string
): Promise<{ message: string; feedback_id: number }> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE_URL}/feedback/`, {
    method: 'POST',
    headers,
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Feedback submission failed');
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
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || 'Admin request failed');
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
  const response = await fetch(`${API_BASE_URL}/admin/users`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create user");
  }

  return response.json();
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
  const response = await fetch(`${API_BASE_URL}/documents/categories`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error("Could not load document categories");
  }
  return response.json();
}

export async function uploadDocument(
  file: File,
  token: string,
  category?: { docType: string; department: string }
): Promise<{
  message: string;
  filename: string;
  stored_as: string;
  size_bytes: number;
  indexing: boolean;
  doc_type: string | null;
  department: string | null;
}> {
  const form = new FormData();
  form.append("file", file);
  if (category) {
    form.append("doc_type", category.docType);
    form.append("department", category.department);
  }
  const response = await fetch(`${API_BASE_URL}/documents/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Upload failed");
  }

  return response.json();
}

export async function updateUserAdmin(
  userId: number,
  patch: Partial<AdminUser & { role?: string }>,
  token: string
): Promise<{ user: AdminUser }> {
  const response = await fetch(`${API_BASE_URL}/admin/users/${userId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(patch),
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Update failed");
  }

  return response.json();
}

export async function approveDocument(
  documentId: number,
  token: string
): Promise<{ message: string; document_id: number; title: string; chunks_updated: number }> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/approve`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Approval failed");
  }

  return response.json();
}
