import { useEffect, useState } from "react";
import type { NotifyVariant } from "../utils/notify";
import styles from "./ToastHost.module.css";

type ToastState = { id: number; message: string; variant: NotifyVariant };

export function ToastHost() {
  const [toast, setToast] = useState<ToastState | null>(null);

  useEffect(() => {
    const onNotify = (ev: Event) => {
      const e = ev as CustomEvent<{ message?: string; variant?: NotifyVariant }>;
      const message = e.detail?.message?.trim();
      if (!message) return;
      const variant = e.detail?.variant ?? "error";
      const id = Date.now();
      setToast({ id, message, variant });
      window.setTimeout(() => {
        setToast((cur) => (cur?.id === id ? null : cur));
      }, 6000);
    };
    window.addEventListener("app:notify", onNotify);
    return () => window.removeEventListener("app:notify", onNotify);
  }, []);

  if (!toast) return null;

  const variantClass = toast.variant === "info" ? styles.info : styles.error;

  return (
    <div className={`${styles.banner} ${variantClass}`} role="alert">
      {toast.message}
    </div>
  );
}
