"use client";

import { useEffect, useState } from "react";

/**
 * A per-browser preference, kept in localStorage. Falls back to the default when
 * storage is unavailable (private windows, blocked site data) or holds junk.
 */
export function useStored<T>(key: string, initial: T, valid: (value: unknown) => value is T) {
  const [value, setValue] = useState<T>(initial);

  useEffect(() => {
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) {
        const parsed: unknown = JSON.parse(stored);
        if (valid(parsed)) setValue(parsed);
      }
    } catch {
      // Keep the default
    }
  }, [key]); // valid is a pure check; key identifies the preference

  const update = (next: T) => {
    setValue(next);
    try {
      localStorage.setItem(key, JSON.stringify(next));
    } catch {
      // Still applies for this page view
    }
  };

  return [value, update] as const;
}
