import { api } from "./client";
import type {
  Conversation,
  ConversationSummary,
  SearchRequest,
  SearchResult,
  ServerLimits,
  UserSettings,
} from "../types";

export const conversationsApi = {
  list: () =>
    api.get<ConversationSummary[]>("/conversations").then((r) => r.data),

  get: (id: string) =>
    api.get<Conversation>(`/conversations/${id}`).then((r) => r.data),

  delete: (id: string) =>
    api.delete(`/conversations/${id}`).then((r) => r.data),

  download: (id: string) =>
    api.get(`/conversations/${id}/download`, { responseType: "blob" }),
};

export const searchApi = {
  search: (params: SearchRequest) =>
    api.post<SearchResult[]>("/search", params).then((r) => r.data),
};

export const settingsApi = {
  getLimits: () =>
    api.get<ServerLimits>("/settings/limits").then((r) => r.data),

  getUserSettings: () =>
    api.get<UserSettings>("/settings/user").then((r) => r.data),

  updateUserSettings: (settings: Partial<UserSettings>) =>
    api.patch<UserSettings>("/settings/user", settings).then((r) => r.data),
};
