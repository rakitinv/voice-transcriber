import { loadSettings } from "./settings/storage";
import { AudioRecorderController } from "./recorder/recorder";
import { registerOAuthMessageListener } from "./auth/oauth";

type Message =
  | { type: "start_recording" }
  | { type: "stop_recording" }
  | { type: "update_settings"; payload: unknown };

const recorder = new AudioRecorderController();

chrome.runtime.onInstalled.addListener(() => {
  console.log("Voice Transcriber extension installed");
});

registerOAuthMessageListener();

chrome.runtime.onMessage.addListener((message: Message, _sender, sendResponse) => {
  (async () => {
    if (message.type === "start_recording") {
      const settings = await loadSettings();

      // In a full implementation we would first create a conversation via the backend
      // and use its ID here. For now, use a random UUID from crypto API.
      const conversationId = crypto.randomUUID();

      await recorder.start({ settings, conversationId });
      sendResponse({ ok: true, conversationId });
    } else if (message.type === "stop_recording") {
      recorder.stop();
      sendResponse({ ok: true });
    } else if (message.type === "update_settings") {
      // Settings are saved directly from popup via storage API; no-op here.
      sendResponse({ ok: true });
    }
  })().catch((err) => {
    console.error("Background error:", err);
    sendResponse({ ok: false, error: String(err) });
  });

  return true; // keep message channel open for async response
});

