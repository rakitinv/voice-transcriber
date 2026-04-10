import { api } from "../api/client";
import type { User } from "../types";

export async function getCurrentUser(): Promise<User | null> {
  try {
    const { data } = await api.get<User>("/auth/me");
    return data;
  } catch {
    return null;
  }
}
