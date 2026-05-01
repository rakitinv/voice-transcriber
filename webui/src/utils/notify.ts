export type NotifyVariant = "error" | "info";

export function notifyError(message: string) {
  const variant: NotifyVariant = "error";
  window.dispatchEvent(new CustomEvent("app:notify", { detail: { message, variant } }));
}

export function notifyInfo(message: string) {
  const variant: NotifyVariant = "info";
  window.dispatchEvent(new CustomEvent("app:notify", { detail: { message, variant } }));
}
