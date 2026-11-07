"use client";

import { useEffect, useRef, useState } from "react";

const HOLD_MS = 120; // Then the CSS transition fades it out over ~500ms

/** Returns a class to apply briefly whenever value rises or falls. */
export function useFlash(value: number | null | undefined): string {
  const previous = useRef(value);
  const [flash, setFlash] = useState("");

  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (value == null || before == null || value === before) return;
    setFlash(value > before ? "flash-up" : "flash-down");
    const timer = setTimeout(() => setFlash(""), HOLD_MS);
    return () => clearTimeout(timer);
  }, [value]);

  return flash;
}
