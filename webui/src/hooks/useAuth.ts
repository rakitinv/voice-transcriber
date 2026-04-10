import { useQuery } from "@tanstack/react-query";
import { getCurrentUser } from "../auth/user";

export const AUTH_QUERY_KEY = ["auth", "me"];

export function useAuth() {
  const { data: user, isLoading, isError } = useQuery({
    queryKey: AUTH_QUERY_KEY,
    queryFn: getCurrentUser,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  return {
    user: user ?? null,
    isAuthenticated: !!user,
    isLoading,
    isError,
  };
}
