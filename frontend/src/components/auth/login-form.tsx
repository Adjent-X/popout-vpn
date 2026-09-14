"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { AuthShell } from "@/components/auth/auth-shell";
import { TurnstileField } from "@/components/auth/turnstile-field";
import { usePublicConfig } from "@/components/brand-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { login } from "@/lib/auth";

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function LoginForm() {
  const router = useRouter();
  const { turnstile_enabled } = usePublicConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [keepSignedIn, setKeepSignedIn] = useState(true);
  const [turnstileToken, setTurnstileToken] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [turnstileKey, setTurnstileKey] = useState(0);

  // Avoid useSearchParams() — it forces a CSR bailout and flashes "Loading…".
  useEffect(() => {
    try {
      if (new URLSearchParams(window.location.search).get("reason") === "expired") {
        setFormError("Your session expired. Please sign in again.");
      }
    } catch {
      /* ignore */
    }
  }, []);

  function validate(): boolean {
    const next: Record<string, string> = {};
    if (!email.trim()) next.email = "Email is required";
    else if (!isValidEmail(email.trim())) next.email = "Enter a valid email";
    if (!password) next.password = "Password is required";
    if (turnstile_enabled && !turnstileToken)
      next.turnstile = "Complete the security check";
    setFieldErrors(next);
    return Object.keys(next).length === 0;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    if (!validate()) return;

    setSubmitting(true);
    try {
      await login({
        email: email.trim(),
        password,
        turnstile_token: turnstile_enabled ? turnstileToken : "",
        keep_signed_in: keepSignedIn,
      });
      router.replace("/dashboard");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Unable to sign in. Try again.";
      setFormError(message);
      setTurnstileToken("");
      setTurnstileKey((k) => k + 1);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Sign in"
      subtitle="Ops access only — VPN client users do not log in here."
      footer={
        <>
          Need an account?{" "}
          <Link
            href="/register"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Register with a token
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={Boolean(fieldErrors.email)}
            className="bg-background/60 font-mono text-sm"
            placeholder="admin@company.com"
          />
          {fieldErrors.email && (
            <p className="font-mono text-xs text-destructive">
              {fieldErrors.email}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={Boolean(fieldErrors.password)}
            className="bg-background/60"
          />
          {fieldErrors.password && (
            <p className="font-mono text-xs text-destructive">
              {fieldErrors.password}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2 pt-1">
          <input
            id="keep-signed-in"
            type="checkbox"
            checked={keepSignedIn}
            onChange={(e) => setKeepSignedIn(e.target.checked)}
            className="size-3.5 accent-[var(--brand-accent)]"
          />
          <Label
            htmlFor="keep-signed-in"
            className="cursor-pointer text-sm font-normal text-muted-foreground"
          >
            Keep me signed in
          </Label>
        </div>

        {turnstile_enabled && (
          <div className="space-y-2">
            <TurnstileField
              key={turnstileKey}
              onToken={setTurnstileToken}
              onExpire={() => setTurnstileToken("")}
              onError={() => {
                setTurnstileToken("");
                setFieldErrors((prev) => ({
                  ...prev,
                  turnstile: "Security check failed — refresh and retry",
                }));
              }}
            />
            {fieldErrors.turnstile && (
              <p className="font-mono text-xs text-destructive">
                {fieldErrors.turnstile}
              </p>
            )}
            {fieldErrors.turnstile && (
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                Tip: ad blockers, DevTools device mode, or connecting through this
                VPN (datacenter IP) often break Turnstile (error 600010). Try a
                normal browser tab without VPN, or disable Turnstile in Server
                settings.
              </p>
            )}
          </div>
        )}

        {formError && (
          <div
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {formError}
          </div>
        )}

        <Button
          type="submit"
          disabled={submitting}
          className="brand-btn-gradient h-11 w-full font-medium shadow-[0_0_24px_color-mix(in_srgb,var(--brand-accent)_25%,transparent)]"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </AuthShell>
  );
}
