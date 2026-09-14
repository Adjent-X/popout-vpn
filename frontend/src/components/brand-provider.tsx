"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { apiFetch } from "@/lib/api";
import {
  BRAND_COLORS_STORAGE_KEY,
  type InitialPublicShell,
} from "@/lib/initial-public-shell";

export type BrandColors = {
  background: string;
  primary: string;
  accent: string;
  accent_bright: string;
};

export type PublicConfig = {
  turnstile_enabled: boolean;
  turnstile_site_key: string;
  brand: {
    name: string;
    product: string;
    site_title: string;
    colors: BrandColors;
  };
  warp_routing_enabled?: boolean;
  duplicate_cn_mode?: boolean;
  public_gate_enabled?: boolean;
  public_gate_unlocked?: boolean;
};

function stripEnvQuotes(value: string): string {
  const raw = value.trim();
  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    return raw.slice(1, -1);
  }
  return raw;
}

function buildDefaults(): PublicConfig {
  return {
    turnstile_enabled:
      (process.env.NEXT_PUBLIC_TURNSTILE_ENABLED ?? "true").toLowerCase() ===
      "true",
    turnstile_site_key: stripEnvQuotes(
      process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? "",
    ),
    brand: {
      name: stripEnvQuotes(process.env.NEXT_PUBLIC_BRAND_NAME ?? "Popout"),
      product: stripEnvQuotes(process.env.NEXT_PUBLIC_BRAND_PRODUCT ?? "VPN"),
      site_title: stripEnvQuotes(
        process.env.NEXT_PUBLIC_SITE_TITLE ?? "Popout VPN Admin",
      ),
      colors: {
        background: stripEnvQuotes(
          process.env.NEXT_PUBLIC_BRAND_COLOR_BG ?? "#0a0e14",
        ),
        primary: stripEnvQuotes(
          process.env.NEXT_PUBLIC_BRAND_COLOR_PRIMARY ?? "#1e3a8a",
        ),
        accent: stripEnvQuotes(
          process.env.NEXT_PUBLIC_BRAND_COLOR_ACCENT ?? "#06b6d4",
        ),
        accent_bright: stripEnvQuotes(
          process.env.NEXT_PUBLIC_BRAND_COLOR_ACCENT_BRIGHT ?? "#67e8f9",
        ),
      },
    },
    warp_routing_enabled:
      (process.env.NEXT_PUBLIC_WARP_ROUTING_ENABLED ?? "true").toLowerCase() !==
      "false",
    duplicate_cn_mode: false,
    public_gate_enabled: false,
    public_gate_unlocked: true,
  };
}

const defaults = buildDefaults();

function shellToConfig(shell: InitialPublicShell): PublicConfig {
  return {
    turnstile_enabled: shell.turnstile_enabled,
    turnstile_site_key: shell.turnstile_site_key,
    brand: {
      name: shell.name,
      product: shell.product,
      site_title: shell.site_title,
      colors: { ...shell.colors },
    },
    warp_routing_enabled: shell.warp_routing_enabled,
    duplicate_cn_mode: shell.duplicate_cn_mode,
    public_gate_enabled: shell.public_gate_enabled,
    public_gate_unlocked: shell.public_gate_unlocked,
  };
}

type BrandContextValue = {
  config: PublicConfig;
  ready: boolean;
  refresh: () => Promise<void>;
};

const BrandContext = createContext<BrandContextValue | null>(null);

function applyBrandCss(colors: BrandColors) {
  const root = document.documentElement;
  root.style.setProperty("--brand-bg", colors.background);
  root.style.setProperty("--brand-primary", colors.primary);
  root.style.setProperty("--brand-accent", colors.accent);
  root.style.setProperty("--brand-accent-bright", colors.accent_bright);
  try {
    localStorage.setItem(BRAND_COLORS_STORAGE_KEY, JSON.stringify(colors));
  } catch {
    /* ignore quota / private mode */
  }
}

function normalizeConfig(data: PublicConfig): PublicConfig {
  const title = (data.brand.site_title || "").trim();
  return {
    ...data,
    brand: {
      ...data.brand,
      site_title: title || defaults.brand.site_title,
    },
  };
}

export function BrandProvider({
  children,
  initialShell,
}: {
  children: React.ReactNode;
  /** Server-fetched public shell so first paint matches live branding. */
  initialShell?: InitialPublicShell | null;
}) {
  const seed = initialShell ? shellToConfig(initialShell) : defaults;
  const [config, setConfig] = useState<PublicConfig>(seed);
  const [ready, setReady] = useState(Boolean(initialShell));

  const refresh = useCallback(async () => {
    try {
      const data = await apiFetch<PublicConfig>(
        "/api/public/config",
        {},
        { auth: false },
      );
      const next = normalizeConfig(data);
      setConfig(next);
      applyBrandCss(next.brand.colors);
    } catch {
      applyBrandCss(seed.brand.colors);
    } finally {
      setReady(true);
    }
  }, [seed.brand.colors]);

  useEffect(() => {
    applyBrandCss(seed.brand.colors);
    void refresh();
    // Seed + refresh once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = useMemo(
    () => ({ config, ready, refresh }),
    [config, ready, refresh],
  );

  return (
    <BrandContext.Provider value={value}>{children}</BrandContext.Provider>
  );
}

export function useBrand() {
  const ctx = useContext(BrandContext);
  if (!ctx) throw new Error("useBrand must be used within BrandProvider");
  return ctx;
}

export function usePublicConfig() {
  return useBrand().config;
}
