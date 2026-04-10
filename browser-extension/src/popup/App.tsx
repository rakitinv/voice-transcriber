import React, { useEffect, useMemo, useState } from "react";

import {
  AudioSource,
  ExtensionSettings,
  LanguageMode,
  RealtimeMode,
  loadSettings,
  updateSettings,
} from "../settings/storage";
import { startOAuthLogin } from "../auth/oauth";

type RecordingStatus = "idle" | "recording";

interface TranscriptLine {
  id: string;
  text: string;
}

export const App: React.FC = () => {
  const [settings, setSettings] = useState<ExtensionSettings | null>(null);
  const [status, setStatus] = useState<RecordingStatus>("idle");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [transcriptLines, setTranscriptLines] = useState<TranscriptLine[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void loadSettings().then(setSettings);
  }, []);

  const transcriptText = useMemo(
    () => transcriptLines.map((l) => l.text).join("\n"),
    [transcriptLines]
  );

  const handleStart = async () => {
    if (!settings) return;
    setError(null);

    chrome.runtime.sendMessage({ type: "start_recording" }, (response) => {
      if (chrome.runtime.lastError) {
        setError(chrome.runtime.lastError.message ?? "Failed to start recording");
        return;
      }
      if (response?.ok) {
        setStatus("recording");
        setConversationId(response.conversationId ?? null);
      } else {
        setError(response?.error ?? "Failed to start recording");
      }
    });
  };

  const handleStop = () => {
    chrome.runtime.sendMessage({ type: "stop_recording" }, (response) => {
      if (!response?.ok) {
        setError(response?.error ?? "Failed to stop recording");
      }
      setStatus("idle");
    });
  };

  const handleDownloadTranscript = () => {
    const blob = new Blob([transcriptText], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "transcript.md";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleGenerateSummary = () => {
    // Summary generation is handled by backend (LLM task) once conversation is uploaded.
    // Here we could call an API endpoint to trigger it; left as a placeholder.
    alert("Summary generation is triggered on the backend (not implemented in popup).");
  };

  const updateLocalSettings = async (partial: Partial<ExtensionSettings>) => {
    if (!settings) return;
    const updated = await updateSettings(partial);
    setSettings(updated);
    chrome.runtime.sendMessage({ type: "update_settings", payload: partial }, () => {});
  };

  const onServerUrlChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ serverUrl: e.target.value });

  const onAudioSourceChange = (e: React.ChangeEvent<HTMLSelectElement>) =>
    void updateLocalSettings({ audioSource: e.target.value as AudioSource });

  const onChunkSizeChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ chunkSizeMs: Number(e.target.value) || 1000 });

  const onRealtimeModeChange = (e: React.ChangeEvent<HTMLSelectElement>) =>
    void updateLocalSettings({ realtimeMode: e.target.value as RealtimeMode });

  const onLanguageModeChange = (e: React.ChangeEvent<HTMLSelectElement>) =>
    void updateLocalSettings({ languageMode: e.target.value as LanguageMode });

  const onLanguageCodeChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ languageCode: e.target.value || null });

  const onTtlChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ ttlDays: Number(e.target.value) || 7 });

  const onMaxDurationChange = (e: React.ChangeEvent<HTMLInputElement>) =>
    void updateLocalSettings({ maxConversationMinutes: Number(e.target.value) || 120 });

  const onLoginClick = (provider: "google" | "yandex") => {
    if (!settings) return;
    startOAuthLogin(settings.serverUrl, provider);
  };

  if (!settings) {
    return <div style={{ padding: 12 }}>Loading settings…</div>;
  }

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: 12, width: 360 }}>
      <h2 style={{ marginTop: 0 }}>Voice Transcriber</h2>

      <section style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={handleStart}
            disabled={status === "recording"}
            style={{ flex: 1 }}
          >
            Start Recording
          </button>
          <button
            onClick={handleStop}
            disabled={status !== "recording"}
            style={{ flex: 1 }}
          >
            Stop Recording
          </button>
        </div>
        <div style={{ marginTop: 4, fontSize: 12 }}>
          Status:{" "}
          <strong style={{ color: status === "recording" ? "green" : "gray" }}>
            {status}
          </strong>
        </div>
      </section>

      <section style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
          <button onClick={handleDownloadTranscript} style={{ flex: 1 }}>
            Download Transcript
          </button>
          <button onClick={handleGenerateSummary} style={{ flex: 1 }}>
            Generate Summary
          </button>
        </div>
        <div
          style={{
            border: "1px solid #ccc",
            borderRadius: 4,
            padding: 8,
            minHeight: 80,
            maxHeight: 200,
            overflowY: "auto",
            fontSize: 12,
            whiteSpace: "pre-wrap",
          }}
        >
          {transcriptLines.length === 0 ? (
            <span style={{ color: "#777" }}>Live transcript will appear here…</span>
          ) : (
            transcriptLines.map((line) => <div key={line.id}>{line.text}</div>)
          )}
        </div>
      </section>

      <section style={{ marginBottom: 12 }}>
        <h3 style={{ margin: "8px 0 4px" }}>Settings</h3>

        <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
          Server URL
          <input
            type="text"
            value={settings.serverUrl}
            onChange={onServerUrlChange}
            style={{ width: "100%" }}
          />
        </label>

        <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
          <button onClick={() => onLoginClick("google")} style={{ flex: 1 }}>
            Login with Google
          </button>
          <button onClick={() => onLoginClick("yandex")} style={{ flex: 1 }}>
            Login with Yandex
          </button>
        </div>

        <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
          Audio source
          <select
            value={settings.audioSource}
            onChange={onAudioSourceChange}
            style={{ width: "100%" }}
          >
            <option value="microphone">Microphone</option>
            <option value="tab">Tab audio</option>
            <option value="system">System audio (not implemented)</option>
          </select>
        </label>

        <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
          Chunk size (ms)
          <input
            type="number"
            min={500}
            max={2000}
            step={100}
            value={settings.chunkSizeMs}
            onChange={onChunkSizeChange}
            style={{ width: "100%" }}
          />
        </label>

        <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
          Realtime mode
          <select
            value={settings.realtimeMode}
            onChange={onRealtimeModeChange}
            style={{ width: "100%" }}
          >
            <option value="chunk">Chunk → ASR → partial transcript</option>
            <option value="windowed">Window buffer → ASR → transcript</option>
          </select>
        </label>

        <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
          Language mode
          <select
            value={settings.languageMode}
            onChange={onLanguageModeChange}
            style={{ width: "100%" }}
          >
            <option value="auto">Auto detect</option>
            <option value="manual">Manual</option>
          </select>
        </label>

        {settings.languageMode === "manual" && (
          <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
            Language code (e.g. en, ru)
            <input
              type="text"
              value={settings.languageCode ?? ""}
              onChange={onLanguageCodeChange}
              style={{ width: "100%" }}
            />
          </label>
        )}

        <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
          TTL (days)
          <input
            type="number"
            min={1}
            max={30}
            value={settings.ttlDays}
            onChange={onTtlChange}
            style={{ width: "100%" }}
          />
        </label>

        <label style={{ display: "block", fontSize: 12, marginBottom: 4 }}>
          Max conversation duration (minutes)
          <input
            type="number"
            min={1}
            max={120}
            value={settings.maxConversationMinutes}
            onChange={onMaxDurationChange}
            style={{ width: "100%" }}
          />
        </label>
      </section>

      {error && (
        <div style={{ color: "red", fontSize: 12, marginTop: 4 }}>{error}</div>
      )}
    </div>
  );
};

