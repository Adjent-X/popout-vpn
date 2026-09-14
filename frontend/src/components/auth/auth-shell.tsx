"use client";

import { BrandMark } from "@/components/brand-mark";
import { useBrand } from "@/components/brand-provider";
import { PoweredByPopout } from "@/components/powered-by";

export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer: React.ReactNode;
}) {
  const { config } = useBrand();
  const siteTitle =
    (config.brand.site_title || "").trim() || "Popout VPN Admin";

  return (
    <div className="auth-grid relative flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <div aria-hidden className="brand-hero-wash pointer-events-none absolute inset-0" />

      <div className="relative z-10 w-full max-w-md">
        <div className="mb-8 text-center">
          <BrandMark href="/" size="lg" />
          <p className="mt-2 font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
            {siteTitle}
          </p>
        </div>

        <div className="auth-glow-border rounded-xl bg-card/90 p-6 backdrop-blur-sm sm:p-8">
          <div className="mb-6 space-y-1">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              {title}
            </h1>
            <p className="text-sm text-muted-foreground">{subtitle}</p>
          </div>
          {children}
        </div>

        <div className="mt-6 text-center text-sm text-muted-foreground">
          {footer}
        </div>

        <div className="mt-8 text-center">
          <PoweredByPopout />
        </div>
      </div>
    </div>
  );
}
