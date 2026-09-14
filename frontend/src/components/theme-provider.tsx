"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import type { AdminPublic } from "@/lib/api";
import { updateTheme as apiUpdateTheme } from "@/lib/api";
import { getStoredAdmin, updateStoredAdmin } from "@/lib/auth";

type Theme = "dark" | "light";

type ThemeContextValue = {
  theme: Theme;
  setTheme: (theme: Theme) => Promise<void>;
  admin: AdminPublic | null;
  setAdmin: (admin: AdminPublic | null) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function applyDomTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [admin, setAdminState] = useState<AdminPublic | null>(null);
  const [theme, setThemeState] = useState<Theme>("dark");

  useEffect(() => {
    const stored = getStoredAdmin();
    if (stored) {
      setAdminState(stored);
      setThemeState(stored.theme);
      applyDomTheme(stored.theme);
    } else {
      applyDomTheme("dark");
    }
  }, []);

  const setAdmin = useCallback((next: AdminPublic | null) => {
    setAdminState(next);
    if (next) {
      updateStoredAdmin(next);
      setThemeState(next.theme);
      applyDomTheme(next.theme);
    }
  }, []);

  const setTheme = useCallback(async (next: Theme) => {
    applyDomTheme(next);
    setThemeState(next);
    const updated = await apiUpdateTheme(next);
    setAdminState(updated);
    updateStoredAdmin(updated);
  }, []);

  const value = useMemo(
    () => ({ theme, setTheme, admin, setAdmin }),
    [theme, setTheme, admin, setAdmin],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
