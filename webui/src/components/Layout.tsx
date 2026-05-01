import { Link, Outlet, useNavigate, NavLink } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { logout } from "../auth/oauth";
import { useQueryClient } from "@tanstack/react-query";
import { AUTH_QUERY_KEY } from "../hooks/useAuth";
import styles from "./Layout.module.css";

export function Layout() {
  const { user, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const handleLogout = () => {
    logout();
    queryClient.setQueryData(AUTH_QUERY_KEY, null);
    navigate("/login", { replace: true });
  };

  if (!isAuthenticated) return null;

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <Link to="/" className={styles.logo}>
          Voice transcriber
        </Link>
        <nav className={styles.nav}>
          <NavLink to="/" end className={({ isActive }) => (isActive ? styles.active : "")}>
            Разговоры
          </NavLink>
          <NavLink to="/search" className={({ isActive }) => (isActive ? styles.active : "")}>
            Поиск
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => (isActive ? styles.active : "")}>
            Настройки
          </NavLink>
        </nav>
        <div className={styles.user}>
          <span className={styles.userName}>{user?.name ?? user?.email ?? "Пользователь"}</span>
          <button type="button" onClick={handleLogout} className={styles.logout}>
            Выйти
          </button>
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}
