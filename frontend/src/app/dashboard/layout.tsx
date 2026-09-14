"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { PoweredByPopout } from "@/components/powered-by";
import { ThemeProvider, useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { fetchMe } from "@/lib/api";
import { getAccessToken, getStoredAdmin, logout } from "@/lib/auth";

function DashboardChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { admin, setAdmin } = useTheme();
  const [ready, setReady] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    const stored = getStoredAdmin();
    if (stored) setAdmin(stored);

    let cancelled = false;
    void (async () => {
      try {
        const me = await fetchMe();
        if (!cancelled) setAdmin(me);
      } catch {
        /* keep stored session; API may be briefly unavailable */
      } finally {
        if (!cancelled) setReady(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [router, setAdmin]);

  useEffect(() => {
    setNavOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setNavOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [navOpen]);

  async function onLogout() {
    await logout();
    router.replace("/login");
  }

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center font-mono text-sm text-muted-foreground">
        Loading…
      </div>
    );
  }

  const isFullAdmin = admin?.role !== "sub_admin";
  const nav = [
    { href: "/dashboard", label: "VPN configs" },
    { href: "/dashboard/analytics", label: "Analytics" },
    ...(isFullAdmin
      ? [
          { href: "/dashboard/attacks", label: "Attacks" },
          { href: "/dashboard/site-settings", label: "Server settings" },
          { href: "/dashboard/admin", label: "Admin" },
        ]
      : []),
    { href: "/dashboard/settings", label: "Account" },
    { href: "/dashboard/docs", label: "API docs" },
  ];

  return (
    <div className="auth-grid flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-3 py-2 sm:gap-3 sm:px-5 sm:py-2.5">
          <div className="flex min-w-0 items-center gap-2 md:gap-5">
            <Button
              type="button"
              variant="outline"
              size="icon-sm"
              className="shrink-0 md:hidden"
              aria-label={navOpen ? "Close menu" : "Open menu"}
              aria-expanded={navOpen}
              onClick={() => setNavOpen((v) => !v)}
            >
              {navOpen ? <X className="size-4" /> : <Menu className="size-4" />}
            </Button>
            <BrandMark href="/dashboard" size="sm" />
            <nav className="hidden items-center gap-0.5 md:flex">
              {nav.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-sm transition-colors",
                    pathname === item.href
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex shrink-0 items-center gap-2 sm:gap-3">
            <span className="hidden max-w-[12rem] truncate font-mono text-xs text-muted-foreground lg:inline">
              {admin?.email}
            </span>
            <Button variant="outline" size="sm" onClick={onLogout}>
              Sign out
            </Button>
          </div>
        </div>
      </header>

      {/* Mobile drawer */}
      <div
        className={cn(
          "fixed inset-0 z-50 md:hidden",
          navOpen ? "pointer-events-auto" : "pointer-events-none",
        )}
        aria-hidden={!navOpen}
      >
        <button
          type="button"
          className={cn(
            "absolute inset-0 bg-black/50 transition-opacity duration-200",
            navOpen ? "opacity-100" : "opacity-0",
          )}
          aria-label="Close menu"
          onClick={() => setNavOpen(false)}
        />
        <aside
          className={cn(
            "absolute top-0 left-0 flex h-full w-[min(18rem,85vw)] flex-col border-r border-border/80 bg-card shadow-xl transition-transform duration-200 ease-out",
            navOpen ? "translate-x-0" : "-translate-x-full",
          )}
        >
          <div className="flex items-center justify-between border-b border-border/60 px-3 py-2.5">
            <BrandMark href="/dashboard" size="sm" />
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Close menu"
              onClick={() => setNavOpen(false)}
            >
              <X className="size-4" />
            </Button>
          </div>
          {admin?.email && (
            <p className="truncate border-b border-border/40 px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
              {admin.email}
            </p>
          )}
          <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto p-2.5">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "rounded-lg px-3 py-2 text-sm transition-colors",
                  pathname === item.href
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
                )}
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="border-t border-border/60 p-2.5">
            <Button
              variant="outline"
              className="w-full"
              onClick={() => void onLogout()}
            >
              Sign out
            </Button>
          </div>
        </aside>
      </div>

      <main className="mx-auto w-full max-w-6xl flex-1 px-3 py-3 sm:px-5 sm:py-5">
        {children}
      </main>
      <footer className="border-t border-border/60 py-2.5 sm:py-3">
        <div className="mx-auto flex max-w-6xl justify-center px-3 sm:px-5">
          <PoweredByPopout />
        </div>
      </footer>
    </div>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ThemeProvider>
      <DashboardChrome>{children}</DashboardChrome>
    </ThemeProvider>
  );
}
