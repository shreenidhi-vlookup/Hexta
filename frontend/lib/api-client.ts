// API client — calls FastAPI directly, no BFF proxy.
// JWT is stored client-side and sent per-request.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001/api/v1';

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
