"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { HistoryCutoff, SettingsResponse } from "@/lib/types";

const CUTOFF_LABELS: Record<HistoryCutoff, string> = {
  never: "Never",
  day: "1 day",
  week: "1 week",
  month: "1 month",
  quarter: "1 quarter",
  year: "1 year",
};

const message = (error: unknown) =>
  error instanceof Error ? error.message : "That didn't work. Try again.";

export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || data) return;
    api.settings().then(setData, () => setError("Couldn't load settings. Try again."));
  }, [open, data]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !root.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const changeCutoff = async (value: HistoryCutoff) => {
    setError(null);
    try {
      setData(await api.updateSettings({ synthetic_history_cutoff: value }));
    } catch (e) {
      setError(message(e));
    }
  };

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="settings-panel"
        onClick={() => {
          setOpen((value) => !value);
          setError(null);
        }}
        className="border border-line px-2 py-0.5 hover:text-ink"
      >
        Settings
      </button>
      {open && (
        <div
          id="settings-panel"
          role="group"
          aria-label="Settings"
          className="absolute top-full right-0 z-20 mt-1 w-72 border border-line bg-raised p-3 text-sm text-ink shadow-lg"
        >
          <label htmlFor="synthetic-history-cutoff" className="block font-medium">
            Stop using simulated history after
          </label>
          <select
            id="synthetic-history-cutoff"
            value={data?.settings.synthetic_history_cutoff ?? ""}
            disabled={!data}
            onChange={(event) => void changeCutoff(event.target.value as HistoryCutoff)}
            className="mt-1 w-full border border-line bg-canvas px-2 py-1"
          >
            {!data && <option value="">Loading…</option>}
            {data?.choices.synthetic_history_cutoff.map((choice) => (
              <option key={choice} value={choice}>
                {CUTOFF_LABELS[choice]}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-muted">
            Once a ticker has this much real price history, analysis ignores its simulated
            history. Charts still show it, labeled.
          </p>
          {error && (
            <p role="alert" className="mt-2 text-down">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
