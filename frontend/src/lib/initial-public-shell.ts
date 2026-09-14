export type BrandColors = {
  background: string;
  primary: string;
  accent: string;
  accent_bright: string;
};

export type InitialPublicShell = {
  colors: BrandColors;
  name: string;
  product: string;
  site_title: string;
  turnstile_enabled: boolean;
  turnstile_site_key: string;
  warp_routing_enabled: boolean;
  duplicate_cn_mode: boolean;
  public_gate_enabled: boolean;
  public_gate_unlocked: boolean;
};

function stripQuotes(value: string | undefined): string {
  const raw = (value ?? "").trim();
  if (
    (raw.startsWith('"') && raw.endsWith('"')) ||
    (raw.startsWith("'") && raw.endsWith("'"))
  ) {
    return raw.slice(1, -1);
  }
  return raw;
}

function envFallback(): InitialPublicShell {
  return {
    colors: {
      background: stripQuotes(process.env.NEXT_PUBLIC_BRAND_COLOR_BG) || "#0a0e14",
      primary:
        stripQuotes(process.env.NEXT_PUBLIC_BRAND_COLOR_PRIMARY) || "#1e3a8a",
      accent:
        stripQuotes(process.env.NEXT_PUBLIC_BRAND_COLOR_ACCENT) || "#06b6d4",
      accent_bright:
        stripQuotes(process.env.NEXT_PUBLIC_BRAND_COLOR_ACCENT_BRIGHT) ||
        "#67e8f9",
    },
    name: stripQuotes(process.env.NEXT_PUBLIC_BRAND_NAME) || "Popout",
    product: stripQuotes(process.env.NEXT_PUBLIC_BRAND_PRODUCT) || "VPN",
    site_title:
      stripQuotes(process.env.NEXT_PUBLIC_SITE_TITLE) || "Popout VPN Admin",
    turnstile_enabled:
      (process.env.NEXT_PUBLIC_TURNSTILE_ENABLED ?? "true").toLowerCase() ===
      "true",
    turnstile_site_key:
      stripQuotes(process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY) || "",
    warp_routing_enabled:
      (process.env.NEXT_PUBLIC_WARP_ROUTING_ENABLED ?? "true").toLowerCase() !==
      "false",
    duplicate_cn_mode: false,
    public_gate_enabled: false,
    public_gate_unlocked: true,
  };
}

function internalApiBase(): string {
  return (
    process.env.INTERNAL_API_URL?.replace(/\/$/, "") ||
    process.env.BACKEND_INTERNAL_URL?.replace(/\/$/, "") ||
    "http://127.0.0.1:8000"
  );
}

export const BRAND_COLORS_STORAGE_KEY = "popout_brand_colors";

/** Blocking head script: restore last-known brand colors before CSS paint. */
export const BRAND_FOUC_SCRIPT = `(function(){try{var raw=localStorage.getItem(${JSON.stringify(BRAND_COLORS_STORAGE_KEY)});if(!raw)return;var c=JSON.parse(raw);if(!c||!c.background)return;var s=document.documentElement.style;s.setProperty('--brand-bg',c.background);s.setProperty('--brand-primary',c.primary);s.setProperty('--brand-accent',c.accent);s.setProperty('--brand-accent-bright',c.accent_bright);}catch(e){}})();`;

/** Live public config for first paint (avoids old-theme FOUC). */
export async function getInitialPublicShell(
  cookieHeader?: string | null,
): Promise<InitialPublicShell> {
  const fallback = envFallback();

  try {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (cookieHeader) headers.Cookie = cookieHeader;
    const res = await fetch(`${internalApiBase()}/api/public/config`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!res.ok) return fallback;
    const data = (await res.json()) as {
      turnstile_enabled?: boolean;
      turnstile_site_key?: string;
      brand?: {
        name?: string;
        product?: string;
        site_title?: string;
        colors?: Partial<BrandColors>;
      };
      warp_routing_enabled?: boolean;
      duplicate_cn_mode?: boolean;
      public_gate_enabled?: boolean;
      public_gate_unlocked?: boolean;
    };
    const c = data.brand?.colors ?? {};
    return {
      colors: {
        background: c.background || fallback.colors.background,
        primary: c.primary || fallback.colors.primary,
        accent: c.accent || fallback.colors.accent,
        accent_bright: c.accent_bright || fallback.colors.accent_bright,
      },
      name: (data.brand?.name || "").trim() || fallback.name,
      product: (data.brand?.product || "").trim() || fallback.product,
      site_title: (data.brand?.site_title || "").trim() || fallback.site_title,
      turnstile_enabled:
        typeof data.turnstile_enabled === "boolean"
          ? data.turnstile_enabled
          : fallback.turnstile_enabled,
      turnstile_site_key:
        data.turnstile_site_key ?? fallback.turnstile_site_key,
      warp_routing_enabled:
        typeof data.warp_routing_enabled === "boolean"
          ? data.warp_routing_enabled
          : fallback.warp_routing_enabled,
      duplicate_cn_mode: Boolean(data.duplicate_cn_mode),
      public_gate_enabled: Boolean(data.public_gate_enabled),
      public_gate_unlocked: data.public_gate_unlocked !== false,
    };
  } catch {
    return fallback;
  }
}

export function brandCssVars(
  colors: BrandColors,
): Record<string, string> {
  return {
    "--brand-bg": colors.background,
    "--brand-primary": colors.primary,
    "--brand-accent": colors.accent,
    "--brand-accent-bright": colors.accent_bright,
  };
}
