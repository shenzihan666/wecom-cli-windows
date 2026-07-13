export interface Conversation {
  userid: string;
  name: string;
  last_time: string;
  last_preview: string;
  has_messages: boolean;
  msg_count: number;
}

export interface ConversationsResponse {
  self_userid: string;
  last_sync: string | null;
  error: string | null;
  conversations: Conversation[];
}

/**
 * Messages are loosely typed on the backend: wecom-cli returns many
 * msgtype-specific shapes (text/image/voice/file/video). We narrow the
 * common fields and keep the rest indexable.
 */
export interface ChatMessage {
  userid?: string;
  msgtype?: string;
  send_time?: string;
  text?: { content?: string };
  [key: string]: unknown;
}

export interface MessagesResponse {
  userid: string;
  name: string;
  messages: ChatMessage[];
  last_sync: string | null;
  self_userid: string;
  users: Record<string, string>;
}

export interface SendResponse {
  ok: boolean;
  message: ChatMessage | null;
  error: string | null;
  raw: Record<string, unknown> | null;
}
