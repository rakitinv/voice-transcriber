import type { ExtensionSettings } from "../settings/storage";
import { AudioRecorderController } from "../recorder/recorder";

const recorder = new AudioRecorderController();

type OffscreenStartMsg = {
  type: "OFFSCREEN_START";
  requestId: string;
  settings: ExtensionSettings;
  conversationId: string;
};

type OffscreenStopMsg = {
  type: "OFFSCREEN_STOP";
};

chrome.runtime.onMessage.addListener((message: OffscreenStartMsg | OffscreenStopMsg) => {
  if (!message || typeof message !== "object") return false;

  if (message.type === "OFFSCREEN_START") {
    void (async () => {
      try {
        await recorder.start({
          settings: message.settings,
          conversationId: message.conversationId,
        });
        await chrome.runtime.sendMessage({
          type: "offscreen_recording_reply",
          requestId: message.requestId,
          ok: true,
        });
      } catch (e) {
        await chrome.runtime.sendMessage({
          type: "offscreen_recording_reply",
          requestId: message.requestId,
          ok: false,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    })();
    return false;
  }

  if (message.type === "OFFSCREEN_STOP") {
    void (async () => {
      try {
        if (recorder.getState() === "recording") {
          await recorder.stop();
        }
      } catch (e) {
        console.error("Offscreen stop error:", e);
      } finally {
        await chrome.runtime.sendMessage({ type: "offscreen_stopped" });
      }
    })();
    return false;
  }

  return false;
});
