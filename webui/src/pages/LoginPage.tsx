import { loginWithGoogle, loginWithYandex } from "../auth/oauth";
import { Button } from "../components/Button";
import styles from "./LoginPage.module.css";

export function LoginPage() {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.title}>Voice Transcriber</h1>
        <p className={styles.subtitle}>Sign in to manage your transcription conversations</p>
        <div className={styles.actions}>
          <Button variant="primary" onClick={loginWithGoogle} className={styles.btn}>
            Sign in with Google
          </Button>
          <Button variant="secondary" onClick={loginWithYandex} className={styles.btn}>
            Sign in with Yandex
          </Button>
        </div>
      </div>
    </div>
  );
}
