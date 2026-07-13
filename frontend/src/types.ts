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

export type AccountState = "stopped" | "running" | "paused";

export interface Account {
  id: string;
  name: string;
  config_dir: string | null;
  self_userid: string;
  last_sync: string | null;
  state: AccountState;
  error: string | null;
}

export interface AccountsResponse {
  accounts: Account[];
}

export interface AccountCreateRequest {
  name?: string;
  config_dir?: string | null;
  self_userid?: string;
}

export interface SettingsResponse {
  poll_sec: number;
  ai_enabled: boolean;
  ai_server_url: string;
  ai_timeout_sec: number;
  ai_system_prompt: string;
  ai_reply_max_length: number;
  ai_history_limit: number;
}

export interface SettingsUpdateRequest {
  poll_sec: number;
  ai_enabled: boolean;
  ai_server_url: string;
  ai_timeout_sec: number;
  ai_system_prompt: string;
  ai_reply_max_length: number;
  ai_history_limit: number;
}

export interface BlacklistItem {
  account_id: string;
  userid: string;
  name: string;
  reason: string;
  created_at: string;
}

export interface BlacklistResponse {
  items: BlacklistItem[];
}

export interface BlacklistAddRequest {
  userid: string;
  name?: string;
  reason?: string;
}
