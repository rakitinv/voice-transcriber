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
    log(logEl, "Checking session…");
    try {
      let settings = await loadSettings();
      const session = await verifyOrRefreshSession(settings);
      if (session.status !== "ok") {
        log(
          logEl,
          session.status === "unauthorized"
            ? "Session expired — log in again from the extension popup."
            : "Could not reach API. Check Server URL in extension settings.",
          "err"
        );
        return;
      }
      settings = session.settings;
      const token = (settings.accessToken ?? "").trim();
      if (!token) {
        log(logEl, "Not signed in. Open the extension popup and log in, then try again.", "err");
        return;
      }
      log(logEl, "Uploading…");
      const res = await postUploadAudio(settings, file, conversationId);
      log(
        logEl,
        `Done.\nconversation_id: ${res.conversation_id}` +
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
