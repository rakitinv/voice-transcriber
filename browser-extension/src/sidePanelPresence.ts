/**
 * Side panel visibility for the toolbar popup: `getContexts` is unreliable for SIDE_PANEL.
 * The side panel page refreshes a timestamp in `chrome.storage.session` while mounted.
 */

export const SIDE_PANEL_PING_MS = 1000;
const LIVE_MS = 4500;

/** Same resolution for popup and side panel so the session key matches. */
export async function getExtensionHostWindowId(): Promise<number | null> {
  try {
    const cur = await chrome.windows.getCurrent();
    if (typeof cur.id === "number") return cur.id;
  } catch {
    // ignore
  }
  try {
    const w = await chrome.windows.getLastFocused({ populate: false });
    return w.id ?? null;
  } catch {
    return null;
  }
}

export function sidePanelPresenceKey(windowId: number): string {
  return `vt_sp_alive_${windowId}`;
}

function suppressCloseKey(windowId: number): string {
  return `vt_sp_suppress_${windowId}`;
}

/** True while popup requested close — blocks heartbeat from reviving `vt_sp_alive_*`. */
export async function isSidePanelCloseSuppressed(windowId: number): Promise<boolean> {
  const area = chrome.storage?.session;
  if (!area) return false;
  try {
    const k = suppressCloseKey(windowId);
    const got = await area.get(k);
    const until = got[k];
    return typeof until === "number" && Date.now() < until;
  } catch {
    return false;
  }
}

/** Popup sets this before closing the panel so a last heartbeat cannot revive presence. */
export async function setSidePanelCloseSuppression(
  windowId: number,
  durationMs: number = 8000
): Promise<void> {
  const area = chrome.storage?.session;
  if (!area) return;
  await area.set({ [suppressCloseKey(windowId)]: Date.now() + durationMs });
}

export async function clearSidePanelCloseSuppression(windowId: number): Promise<void> {
  const area = chrome.storage?.session;
  if (!area) return;
  await area.remove(suppressCloseKey(windowId));
}

export async function touchSidePanelPresence(windowId: number): Promise<void> {
  if (await isSidePanelCloseSuppressed(windowId)) return;
  const area = chrome.storage?.session;
  if (!area) return;
  await area.set({ [sidePanelPresenceKey(windowId)]: Date.now() });
}

export async function clearSidePanelPresence(windowId: number): Promise<void> {
  const area = chrome.storage?.session;
  if (!area) return;
  await area.remove(sidePanelPresenceKey(windowId));
}

/** True if the recording side panel is mounted in this browser window (fresh heartbeat). */
export async function isSidePanelPresentForWindow(windowId: number): Promise<boolean> {
  if (await isSidePanelCloseSuppressed(windowId)) return false;
  const area = chrome.storage?.session;
  if (!area) return false;
  try {
    const key = sidePanelPresenceKey(windowId);
    const got = await area.get(key);
    const ts = got[key];
    if (typeof ts !== "number") return false;
    return Date.now() - ts < LIVE_MS;
  } catch {
    return false;
  }
}
