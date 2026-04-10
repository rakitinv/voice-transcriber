import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  conversationsApi,
  searchApi,
  settingsApi,
} from "../api/conversations";
import type { SearchRequest, UserSettings } from "../types";

export const CONVERSATIONS_QUERY_KEY = ["conversations"];
export const CONVERSATION_QUERY_KEY = (id: string) => ["conversations", id];
export const SETTINGS_LIMITS_KEY = ["settings", "limits"];
export const SETTINGS_USER_KEY = ["settings", "user"];

export function useConversations() {
  return useQuery({
    queryKey: CONVERSATIONS_QUERY_KEY,
    queryFn: conversationsApi.list,
  });
}

export function useConversation(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: CONVERSATION_QUERY_KEY(id ?? ""),
    queryFn: () => conversationsApi.get(id!),
    enabled: !!id && enabled,
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => conversationsApi.delete(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: CONVERSATIONS_QUERY_KEY });
    },
  });
}

export function useSearch() {
  return useMutation({
    mutationFn: (params: SearchRequest) => searchApi.search(params),
  });
}

export function useSettingsLimits() {
  return useQuery({
    queryKey: SETTINGS_LIMITS_KEY,
    queryFn: settingsApi.getLimits,
  });
}

export function useUserSettings() {
  return useQuery({
    queryKey: SETTINGS_USER_KEY,
    queryFn: settingsApi.getUserSettings,
  });
}

export function useUpdateUserSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings: Partial<UserSettings>) =>
      settingsApi.updateUserSettings(settings),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SETTINGS_USER_KEY });
    },
  });
}
