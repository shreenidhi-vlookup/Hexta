// Lightweight, client-only conversation history (24h TTL).
// Stays in localStorage so the app stays light; the API is isolated behind
// this module so it can be swapped for server-side persistence later.

import { getCurrentUserId } from "./auth";

export const CHATS_STORAGE_KEY = "hexa_recent_chats";
export const CHAT_TTL_MS = 24 * 60 * 60 * 1000;

export type ChatRole = "user" | "assistant";

export interface ChatTurn {
  role: ChatRole;
  content: string;
}

export interface RecentChat {
  id: string;
  title: string;
  createdAt: number;
  turns: ChatTurn[];
}

// Chats are namespaced per user so staff and admin (and different users)
// sharing a browser never see or clear each other's history.
function chatsKey(): string {
  const userId = getCurrentUserId();
  return userId != null ? `${CHATS_STORAGE_KEY}_${userId}` : CHATS_STORAGE_KEY;
}

function safeParse(): RecentChat[] {
  try {
    const raw = localStorage.getItem(chatsKey());
    if (!raw) return [];
    const value = JSON.parse(raw);
    return Array.isArray(value) ? (value as RecentChat[]) : [];
  } catch {
    return [];
  }
}

function persist(chats: RecentChat[]) {
  try {
    localStorage.setItem(chatsKey(), JSON.stringify(chats));
  } catch {
    // ignore quota errors — never block the chat UI
  }
}

function prune(chats: RecentChat[]): RecentChat[] {
  const now = Date.now();
  const fresh = chats.filter((c) => now - c.createdAt <= CHAT_TTL_MS);
  if (fresh.length !== chats.length) persist(fresh);
  return fresh;
}

export function listRecentChats(): RecentChat[] {
  return prune(safeParse()).sort((a, b) => b.createdAt - a.createdAt);
}

// One-time migration: chats created before per-user namespacing live under the
// bare shared key (hexa_recent_chats). Claim them for the first logged-in user
// so the pre-fix history isn't lost. The legacy key is removed, making this a
// single claim — whichever user logs in first after the fix gets the history.
export function migrateLegacyChats(): void {
  const userId = getCurrentUserId();
  if (userId == null) return;

  const legacyKey = CHATS_STORAGE_KEY;
  let legacy: RecentChat[];
  try {
    const raw = localStorage.getItem(legacyKey);
    if (!raw) return;
    const value = JSON.parse(raw);
    legacy = Array.isArray(value) ? (value as RecentChat[]) : [];
  } catch {
    return;
  }
  if (legacy.length === 0) return;

  try {
    const ownRaw = localStorage.getItem(chatsKey());
    if (ownRaw) return; // user already has chats — never overwrite

    localStorage.setItem(chatsKey(), JSON.stringify(legacy));
    localStorage.removeItem(legacyKey);
  } catch {
    // ignore quota/storage errors — never block the chat UI
  }
}

export function saveChat(chat: RecentChat): void {
  const chats = prune(safeParse()).filter((c) => c.id !== chat.id);
  chats.unshift(chat);
  persist(chats.slice(0, 30));
}

export function deleteChat(id: string): void {
  persist(safeParse().filter((c) => c.id !== id));
}

export function clearAllChats(): void {
  persist([]);
}

export function getChat(id: string): RecentChat | undefined {
  return listRecentChats().find((c) => c.id === id);
}

export function deriveTitle(turns: ChatTurn[]): string {
  const first = turns.find((t) => t.role === "user");
  const text = first?.content?.trim();
  if (!text) return "New chat";
  return text.length > 40 ? `${text.slice(0, 40)}…` : text;
}

export function newChatId(): string {
  return `c_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
