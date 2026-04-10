/** Conversation list item from GET /conversations */
export interface ConversationSummary {
  id: string;
  date: string;
  duration: number;
  language: string;
}

/** Single conversation with transcript from GET /conversations/{id} */
export interface Conversation {
  id: string;
  date: string;
  duration: number;
  language: string;
  transcript: TranscriptSegment[];
  summary?: string;
}

/** Speaker segment with timestamps */
export interface TranscriptSegment {
  speaker: string;
  start: number;
  end: number;
  text: string;
}

/** Search request/response */
export interface SearchRequest {
  text?: string;
  semantic?: boolean;
}

export interface SearchResult {
  conversationId: string;
  date: string;
  duration: number;
  language: string;
  matches: TranscriptSegment[];
}

/** Server limits (settings) */
export interface ServerLimits {
  maxDuration: number;
  maxTtl: number;
  maxFileSize: number;
}

/** User settings */
export interface UserSettings {
  defaultLanguage: string;
  defaultTtl: number;
  searchMode: "text" | "semantic";
}

/** Auth user (after OAuth) */
export interface User {
  id: string;
  email?: string;
  name?: string;
  provider?: "google" | "yandex";
}
