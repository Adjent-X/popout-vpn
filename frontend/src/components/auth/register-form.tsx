"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AuthShell } from "@/components/auth/auth-shell";
import { TurnstileField } from "@/components/auth/turnstile-field";
import { usePublicConfig } from "@/components/brand-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { register } from "@/lib/auth";

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function RegisterForm() {
  const router = useRouter();
  const { turnstile_enabled } = usePublicConfig();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [registrationToken, setRegistrationToken] = useState("");
  const [turnstileToken, setTurnstileToken] = useState("");
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [turnstileKey, setTurnstileKey] = useState(0);

  function validate(): boolean {
    const next: Record<string, string> = {};
    if (!email.trim()) next.email = "Email is required";
    else if (!isValidEmail(email.trim())) next.email = "Enter a valid email";
    if (!password) next.password = "Password is required";
    else if (password.length < 12)
      next.password = "Password must be at least 12 characters";
    if (password !== confirmPassword)
      next.confirmPassword = "Passwords do not match";
    if (!registrationToken.trim())
      next.registrationToken = "Registration token is required";
    else if (registrationToken.trim().length < 16)
      next.registrationToken = "Token looks too short";
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
      await register({
        email: email.trim(),
        password,
        registration_token: registrationToken.trim(),
        turnstile_token: turnstile_enabled ? turnstileToken : "",
      });
      router.replace("/dashboard");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Unable to register. Try again.";
      setFormError(message);
      setTurnstileToken("");
      setTurnstileKey((k) => k + 1);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell
      title="Create admin account"
      subtitle="Registration requires a single-use invite token from an administrator."
      footer={
        <>
          Already registered?{" "}
          <Link
            href="/login"
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <div className="space-y-2">
          <Label htmlFor="registration_token">Registration token</Label>
          <Input
            id="registration_token"
            type="text"
            autoComplete="off"
            spellCheck={false}
            value={registrationToken}
            onChange={(e) => setRegistrationToken(e.target.value)}
            aria-invalid={Boolean(fieldErrors.registrationToken)}
            className="bg-background/60 font-mono text-sm"
            placeholder="Paste your invite token"
          />
          {fieldErrors.registrationToken && (
            <p className="font-mono text-xs text-destructive">
              {fieldErrors.registrationToken}
            </p>
          )}
        </div>

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
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={Boolean(fieldErrors.password)}
            className="bg-background/60"
          />
          {fieldErrors.password ? (
            <p className="font-mono text-xs text-destructive">
              {fieldErrors.password}
            </p>
          ) : (
            <p className="font-mono text-[11px] text-muted-foreground">
              Minimum 12 characters
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="confirm_password">Confirm password</Label>
          <Input
            id="confirm_password"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            aria-invalid={Boolean(fieldErrors.confirmPassword)}
            className="bg-background/60"
          />
          {fieldErrors.confirmPassword && (
            <p className="font-mono text-xs text-destructive">
              {fieldErrors.confirmPassword}
            </p>
          )}
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
          {submitting ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </AuthShell>
  );
}
