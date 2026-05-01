import { loginWithGoogle, loginWithYandex } from "../auth/oauth";
import { Button } from "../components/Button";
import styles from "./LoginPage.module.css";

export function LoginPage() {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Voice transcriber</h1>
        <p className={styles.subtitle}>Войдите, чтобы управлять записями и расшифровками</p>
        <div className={styles.actions}>
          <Button variant="primary" onClick={loginWithGoogle} className={styles.btn}>
            Войти через Google
          </Button>
          <Button variant="secondary" onClick={loginWithYandex} className={styles.btn}>
            Войти через Яндекс
          </Button>
        </div>
      </div>
    </div>
  );
}
