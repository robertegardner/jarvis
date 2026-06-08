// Shapes mirroring the backend (jarvis/web/session.py messages + api.py JSON).

export interface ServerInfo {
  name: string;
  host: string;
  posture: string;
  description: string;
}

export interface ServerRow {
  name: string;
  host: string;
  user: string;
  port: number;
  identity_file: string | null;
  posture: string;
  description: string;
}

export interface InventoryPut {
  servers: ServerRow[];
}

export interface PermissionRule {
  index: number;
  server: string;
  match: string;
  value: string;
  note: string;
  created: string;
}

export interface TaskEntry {
  ts: string;
  server: string;
  command: string;
  read_only: boolean;
  decision: string;
  exit_code: number | null;
  summary: string;
}

export interface ApprovalRequest {
  id: string;
  server: string;
  posture: string;
  command: string;
  purpose: string;
  reason: string;
  binary: string;
}

// One entry in the conversation feed.
export type FeedItem =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "tool_use"; tool: string; server?: string; command?: string; purpose?: string; note?: string }
  | { kind: "tool_result"; text: string; is_error: boolean }
  | { kind: "notice"; text: string }
  | { kind: "error"; text: string };

export type Choice = "y" | "n" | "b" | "e" | "g";
