import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  conversationsApi,
  searchApi,
  settingsApi,
} from "../api/conversations";
import { notifyAxiosUploadError } from "../utils/downloadErrors";
import { notifyInfo } from "../utils/notify";
import type { UserSettings } from "../types";

export const CONVERSATIONS_QUERY_KEY = ["conversations"];
export const CONVERSATION_QUERY_KEY = (id: string, tier: string) => [
  "conversations",
  id,
  tier,
];
export const SETTINGS_LIMITS_KEY = ["settings", "limits"];
export const SETTINGS_USER_KEY = ["settings", "user"];
export const SETTINGS_OAUTH_IDENTITIES_KEY = ["settings", "oauth-identities"];

export function useConversations() {
  return useQuery({
    queryKey: CONVERSATIONS_QUERY_KEY,
    queryFn: conversationsApi.list,
  });
}

export function useConversation(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: CONVERSATION_QUERY_KEY(id ?? "", "auto"),
    queryFn: () => conversationsApi.get(id!, { tier: "auto" }),
    enabled: !!id && enabled,
    refetchInterval: (q) => {
      const d = q.state.data;
      if (d?.refetchRecommended) return 2800;
      const ss = d?.recordingSessionSummaryStatus;
      if (ss === "pending" || ss === "running") return 3500;
      return false;
    },
  });
}

export function useConversationTier(
  id: string | undefined,
  tier: "auto" | "fast" | "final",
  enabled = true
) {
  return useQuery({
    queryKey: CONVERSATION_QUERY_KEY(id ?? "", tier),
    queryFn: () => conversationsApi.get(id!, { tier }),
    enabled: !!id && enabled,
    refetchInterval: (q) => {
      const d = q.state.data;
      if (d?.refetchRecommended) return 2800;
      const ss = d?.recordingSessionSummaryStatus;
      if (ss === "pending" || ss === "running") return 3500;
      return false;
    },
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

/** Пакетная загрузка файла: тот же `POST /api/upload`, что у CLI `upload`. */
export function useUploadAudio() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (file: File) => conversationsApi.uploadAudio(file),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: CONVERSATIONS_QUERY_KEY });
      notifyInfo("Файл принят в обработку.");
      navigate(`/conversations/${data.conversation_id}`);
    },
    onError: (err) => {
      void notifyAxiosUploadError(err);
    },
  });
}

export function useSearch() {
  return useMutation({
    mutationFn: ({ text, semantic }: { text: string; semantic: boolean }) =>
      searchApi.search(text, semantic),
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

export function useOAuthIdentities() {
  return useQuery({
    queryKey: SETTINGS_OAUTH_IDENTITIES_KEY,
    queryFn: settingsApi.listOAuthIdentities,
  });
}
