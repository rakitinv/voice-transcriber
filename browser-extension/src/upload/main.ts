import { verifyOrRefreshSession } from "../auth/oauth";
import { postUploadAudio } from "../api/upload";
import { loadSettings } from "../settings/storage";

function log(el: HTMLElement, msg: string, cls?: string): void {
  el.textContent = msg;
  el.className = cls ?? "";
}

async function main(): Promise<void> {
  const logEl = document.getElementById("log");
  const input = document.getElementById("file") as HTMLInputElement | null;
  if (!logEl || !input) return;

  const params = new URLSearchParams(window.location.search);
  const conversationId = params.get("conversation_id");

  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (!file) return;
    log(logEl, "Проверка сессии…");
    try {
      let settings = await loadSettings();
      const session = await verifyOrRefreshSession(settings);
      if (session.status !== "ok") {
        log(
          logEl,
          session.status === "unauthorized"
            ? "Сессия истекла — войдите снова через всплывающее окно расширения."
            : "Не удалось связаться с API. Проверьте URL сервера в настройках расширения.",
          "err"
        );
        return;
      }
      settings = session.settings;
      const token = (settings.accessToken ?? "").trim();
      if (!token) {
        log(logEl, "Вы не вошли. Откройте всплывающее окно расширения, выполните вход и повторите.", "err");
        return;
      }
      log(logEl, "Загрузка…");
      const res = await postUploadAudio(settings, file, conversationId);
      log(
        logEl,
        `Готово.\nconversation_id: ${res.conversation_id}` +
          (res.audio_object_ext ? `\naudio_object_ext: ${res.audio_object_ext}` : ""),
        "ok"
      );
    } catch (e) {
      log(logEl, e instanceof Error ? e.message : String(e), "err");
    } finally {
      input.value = "";
    }
  });
}

void main();
