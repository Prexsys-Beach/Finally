"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { Settings, SettingsResponse } from "./types";

const CHANGED = "finally:settings";

/** Save settings and tell every component showing them. */
export async function saveSettings(changes: Partial<Settings>): Promise<SettingsResponse> {
  const saved = await api.updateSettings(changes);
  window.dispatchEvent(new CustomEvent<SettingsResponse>(CHANGED, { detail: saved }));
  return saved;
}

/** Follow settings saved anywhere on the page. */
export function onSettingsSaved(listener: (saved: SettingsResponse) => void): () => void {
  const handler = (event: Event) => listener((event as CustomEvent<SettingsResponse>).detail);
  window.addEventListener(CHANGED, handler);
  return () => window.removeEventListener(CHANGED, handler);
}

/** Current settings, loaded once and kept in step with saves elsewhere. Null until loaded. */
export function useSettings() {
  const [data, setData] = useState<SettingsResponse | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.settings().then(
      (loaded) => !cancelled && setData(loaded),
      () => undefined,
    );
    const stop = onSettingsSaved(setData);
    return () => {
      cancelled = true;
      stop();
    };
  }, []);
  return data;
}
