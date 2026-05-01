import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { apiBaseUrlFromEnv } from "./apiBase";

const baseURL = apiBaseUrlFromEnv();

export const api = axios.create({
  baseURL,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  if (config.data instanceof FormData) {
    config.headers.delete("Content-Type");
  }
  return config;
});

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const rt = localStorage.getItem("refresh_token");
  if (!rt?.trim()) return null;

  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const { data } = await axios.post<{ access_token: string; refresh_token?: string | null }>(
          `${baseURL}/auth/refresh`,
          { refresh_token: rt.trim() },
          { headers: { "Content-Type": "application/json" }, withCredentials: true }
        );
        localStorage.setItem("access_token", data.access_token);
        if (data.refresh_token) localStorage.setItem("refresh_token", data.refresh_token);
        api.defaults.headers.common.Authorization = `Bearer ${data.access_token}`;
        return data.access_token;
      } catch {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        delete api.defaults.headers.common.Authorization;
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
  }

  return refreshInFlight;
}

api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const original = err.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    const status = err.response?.status;

    if (!original || status !== 401 || original._retry) {
      return Promise.reject(err);
    }

    if (String(original.url ?? "").includes("/auth/refresh")) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      delete api.defaults.headers.common.Authorization;
      window.dispatchEvent(new CustomEvent("auth:logout"));
      return Promise.reject(err);
    }

    original._retry = true;
    const newTok = await refreshAccessToken();
    if (!newTok) {
      window.dispatchEvent(new CustomEvent("auth:logout"));
      return Promise.reject(err);
    }

    original.headers.Authorization = `Bearer ${newTok}`;
    return api(original);
  }
);
