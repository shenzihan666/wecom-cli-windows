import type {
  Account,
  AccountCreateRequest,
  AccountsResponse,
  BlacklistAddRequest,
  BlacklistItem,
  BlacklistResponse,
  ConversationsResponse,
  MessagesResponse,
  SendResponse,
  SettingsResponse,
  SettingsUpdateRequest,
} from "./types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (await res.json()) as T | { detail?: string };
  if (!res.ok) {
    throw new Error((data as { detail?: string }).detail ?? "request failed");
  }
  return data as T;
}

export function fetchConversations(accountId: string): Promise<ConversationsResponse> {
  return getJson<ConversationsResponse>(
    `/api/conversations?account=${encodeURIComponent(accountId)}`,
  );
}

export function fetchMessages(accountId: string, userid: string): Promise<MessagesResponse> {
  return getJson<MessagesResponse>(
    `/api/messages?account=${encodeURIComponent(accountId)}&userid=${encodeURIComponent(userid)}`,
  );
}

export async function sendMessage(
  accountId: string,
  userid: string,
  content: string,
): Promise<SendResponse> {
  const res = await fetch(`/api/send?account=${encodeURIComponent(accountId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userid, content }),
  });
  return (await res.json()) as SendResponse;
}

export function mediaUrl(file: string): string {
  return `/media/${encodeURIComponent(file)}`;
}

export function fetchAccounts(): Promise<AccountsResponse> {
  return getJson<AccountsResponse>("/api/accounts");
}

export function createAccount(body: AccountCreateRequest): Promise<Account> {
  return postJson<Account>("/api/accounts", body);
}

export async function deleteAccount(accountId: string): Promise<void> {
  const res = await fetch(`/api/accounts/${encodeURIComponent(accountId)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? "delete failed");
  }
}

export function startAccount(accountId: string): Promise<Account> {
  return postJson<Account>(`/api/accounts/${encodeURIComponent(accountId)}/start`);
}

export function pauseAccount(accountId: string): Promise<Account> {
  return postJson<Account>(`/api/accounts/${encodeURIComponent(accountId)}/pause`);
}

export function fetchSettings(): Promise<SettingsResponse> {
  return getJson<SettingsResponse>("/api/settings");
}

export async function updateSettings(body: SettingsUpdateRequest): Promise<SettingsResponse> {
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json()) as SettingsResponse | { detail?: string };
  if (!res.ok) {
    throw new Error((data as { detail?: string }).detail ?? "save failed");
  }
  return data as SettingsResponse;
}

export function fetchBlacklist(accountId: string): Promise<BlacklistResponse> {
  return getJson<BlacklistResponse>(
    `/api/blacklist?account=${encodeURIComponent(accountId)}`,
  );
}

export function addBlacklist(
  accountId: string,
  body: BlacklistAddRequest,
): Promise<BlacklistItem> {
  return postJson<BlacklistItem>(
    `/api/blacklist?account=${encodeURIComponent(accountId)}`,
    body,
  );
}

export async function removeBlacklist(accountId: string, userid: string): Promise<void> {
  const res = await fetch(
    `/api/blacklist/${encodeURIComponent(userid)}?account=${encodeURIComponent(accountId)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? "remove failed");
  }
}
