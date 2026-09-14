"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { useBrand } from "@/components/brand-provider";

const PAGE_LABELS: Record<string, string> = {
  "/": "",
  "/login": "Sign in",
  "/register": "Register",
  "/dashboard": "VPN configs",
  "/dashboard/analytics": "Analytics",
  "/dashboard/attacks": "Attacks",
  "/dashboard/site-settings": "Server settings",
  "/dashboard/admin": "Admin",
  "/dashboard/settings": "Account settings",
  "/dashboard/docs": "API docs",
};

/** Keeps the browser tab title in sync with Server settings → Site title. */
export function DocumentTitle() {
  const pathname = usePathname();
  const { config } = useBrand();
  const siteTitle =
    (config.brand.site_title || "").trim() || "Popout VPN Admin";

  useEffect(() => {
    const page = PAGE_LABELS[pathname] ?? "";
    document.title = page ? `${page} · ${siteTitle}` : siteTitle;
  }, [pathname, siteTitle]);

  return null;
}
