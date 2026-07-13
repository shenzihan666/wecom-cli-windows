import type { ConversationsResponse, MessagesResponse, SendResponse } from "./types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  return (await res.json()) as T;
}

export function fetchConversations(): Promise<ConversationsResponse> {
  return getJson<ConversationsResponse>("/api/conversations");
}

export function fetchMessages(userid: string): Promise<MessagesResponse> {
  return getJson<MessagesResponse>(`/api/messages?userid=${encodeURIComponent(userid)}`);
}

export async function sendMessage(userid: string, content: string): Promise<SendResponse> {
  const res = await fetch("/api/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userid, content }),
  });
  return (await res.json()) as SendResponse;
}

export function mediaUrl(file: string): string {
  return `/media/${encodeURIComponent(file)}`;
}
