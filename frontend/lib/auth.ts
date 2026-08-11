// Client-side JWT auth management
// No server-side sessions — token lives in browser localStorage.

import { verifyToken } from './api-client';

export interface UserSession {
  token: string;
  userId: number;
  email: string;
}

const TOKEN_KEY = 'hexa_auth_token';

export function storeToken(token: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export function getToken(): string | null {
  if (typeof window !== 'undefined') {
    return localStorage.getItem(TOKEN_KEY);
  }
  return null;
}

export function clearToken(): void {
  if (typeof window !== 'undefined') {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export async function getSession(): Promise<UserSession | null> {
  const token = getToken();
  if (!token) return null;

  try {
    const result = await verifyToken(token);
    if (!result.valid) {
      clearToken();
      return null;
    }
    return {
      token,
      userId: result.user_id ?? 0,
      email: result.email ?? '',
    };
  } catch {
    clearToken();
    return null;
  }
}

export function getTokenRole(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return typeof payload.role === 'string' ? payload.role : null;
  } catch {
    return null;
  }
}

export function getTokenUserId(token: string): number | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const sub = payload.sub;
    const id = Number(sub);
    return Number.isFinite(id) ? id : null;
  } catch {
    return null;
  }
}

export function getCurrentUserId(): number | null {
  const token = getToken();
  return token ? getTokenUserId(token) : null;
}

export const ADMIN_ROLES = new Set(["super_admin", "admin"]);

export function isAdminRole(role: string | null): boolean {
  return role !== null && ADMIN_ROLES.has(role);
}

export function isTokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const exp = payload.exp;
    if (!exp) return false;
    return Date.now() >= exp * 1000 - 60000; // 1 min buffer
  } catch {
    return true;
  }
}
