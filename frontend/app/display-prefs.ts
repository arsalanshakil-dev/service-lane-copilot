"use client";

// Per-browser display preferences (issue #46): theme and the time zone used to show times of day.

import { useCallback, useEffect, useState } from "react";

export const THEME_STORAGE_KEY = "service-lane-theme";
export const TIME_ZONE_STORAGE_KEY = "service-lane-time-zone";
const THEME_EVENT = "service-lane-theme-change";
const TIME_ZONE_EVENT = "service-lane-time-zone-change";

export type ThemePref = "light" | "dark" | "system";

function read(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function write(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage can be unavailable (private mode); the choice still applies to this page view.
  }
}

// ---- Theme ----

function readThemePref(): ThemePref {
  const saved = read(THEME_STORAGE_KEY);
  return saved === "dark" || saved === "system" ? saved : "light";
}

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches === true;
}

/** Apply a theme preference to the page (System follows the operating system). */
export function applyTheme(pref: ThemePref) {
  const resolved = pref === "system" ? (systemPrefersDark() ? "dark" : "light") : pref;
  document.documentElement.dataset.theme = resolved;
}

export function setThemePref(pref: ThemePref) {
  write(THEME_STORAGE_KEY, pref);
  applyTheme(pref);
  window.dispatchEvent(new Event(THEME_EVENT));
}

export function useThemePref(): { pref: ThemePref; setPref: (pref: ThemePref) => void } {
  const [pref, setPrefState] = useState<ThemePref>("light");
  useEffect(() => {
    const sync = () => setPrefState(readThemePref());
    sync();
    // Keep "System" in step with the OS while the page is open.
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const onSystemChange = () => {
      if (readThemePref() === "system") applyTheme("system");
    };
    media?.addEventListener?.("change", onSystemChange);
    window.addEventListener(THEME_EVENT, sync);
    return () => {
      media?.removeEventListener?.("change", onSystemChange);
      window.removeEventListener(THEME_EVENT, sync);
    };
  }, []);
  return { pref, setPref: setThemePref };
}

// ---- Time zone ----

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function supportedTimeZones(): string[] {
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    const zones = intl.supportedValuesOf?.("timeZone") ?? [];
    return zones.length ? zones : [browserTimeZone(), "UTC"];
  } catch {
    return [browserTimeZone(), "UTC"];
  }
}

function isValidZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

export function useTimeZone(): { pref: string; timeZone: string; setPref: (zone: string) => void } {
  const [pref, setPrefState] = useState("");
  const [fallback, setFallback] = useState("UTC");
  useEffect(() => {
    setFallback(browserTimeZone());
    const sync = () => setPrefState(read(TIME_ZONE_STORAGE_KEY));
    sync();
    window.addEventListener(TIME_ZONE_EVENT, sync);
    return () => window.removeEventListener(TIME_ZONE_EVENT, sync);
  }, []);
  const setPref = useCallback((zone: string) => {
    write(TIME_ZONE_STORAGE_KEY, zone);
    setPrefState(zone);
    window.dispatchEvent(new Event(TIME_ZONE_EVENT));
  }, []);
  const timeZone = pref && isValidZone(pref) ? pref : fallback;
  return { pref, timeZone, setPref };
}

function formatWith(iso: string, timeZone: string, options: Intl.DateTimeFormatOptions): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  try {
    return new Intl.DateTimeFormat("en-US", { ...options, timeZone, timeZoneName: "short" }).format(parsed);
  } catch {
    return parsed.toISOString();
  }
}

/** "Nov 6, 2026, 1:53 PM GMT+5" in the chosen time zone. */
export function formatDateTime(iso: string, timeZone: string): string {
  return formatWith(iso, timeZone, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** "9:30 AM GMT+5" in the chosen time zone. */
export function formatTimeOfDay(iso: string, timeZone: string): string {
  return formatWith(iso, timeZone, { hour: "numeric", minute: "2-digit" });
}
