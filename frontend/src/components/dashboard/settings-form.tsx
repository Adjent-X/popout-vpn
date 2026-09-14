"use client";

import { useState } from "react";

import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, updateCredentials } from "@/lib/api";

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function SettingsForm() {
  const { theme, setTheme, admin, setAdmin } = useTheme();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [credBusy, setCredBusy] = useState(false);
  const [credMessage, setCredMessage] = useState<string | null>(null);
  const [credError, setCredError] = useState<string | null>(null);

  async function onThemeChange(next: "dark" | "light") {
    if (next === theme) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await setTheme(next);
      setMessage(
        next === "dark"
          ? "Dark theme saved to your account."
          : "Light theme saved to your account.",
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not save theme preference.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function onCredentialsSubmit(e: React.FormEvent) {
    e.preventDefault();
    setCredError(null);
    setCredMessage(null);

    const emailTrimmed = newEmail.trim();
    const wantsEmail = Boolean(emailTrimmed);
    const wantsPassword = Boolean(newPassword);

    if (!currentPassword) {
      setCredError("Enter your current password to make changes.");
      return;
    }
    if (!wantsEmail && !wantsPassword) {
      setCredError("Enter a new email and/or a new password.");
      return;
    }
    if (wantsEmail && !isValidEmail(emailTrimmed)) {
      setCredError("Enter a valid email address.");
      return;
    }
    if (wantsPassword) {
      if (newPassword.length < 12) {
        setCredError("New password must be at least 12 characters.");
        return;
      }
      if (newPassword !== confirmPassword) {
        setCredError("New password and confirmation do not match.");
        return;
      }
    }

    setCredBusy(true);
    try {
      const updated = await updateCredentials({
        current_password: currentPassword,
        ...(wantsEmail ? { new_email: emailTrimmed } : {}),
        ...(wantsPassword ? { new_password: newPassword } : {}),
      });
      setAdmin(updated);
      setCurrentPassword("");
      setNewEmail("");
      setNewPassword("");
      setConfirmPassword("");
      const parts: string[] = [];
      if (wantsEmail) parts.push("email");
      if (wantsPassword) parts.push("password");
      setCredMessage(`Updated ${parts.join(" and ")}.`);
    } catch (err) {
      setCredError(
        err instanceof ApiError
          ? err.message
          : "Could not update account credentials.",
      );
    } finally {
      setCredBusy(false);
    }
  }

  const roleLabel =
    admin?.role === "sub_admin"
      ? "Sub-admin"
      : admin?.role === "admin"
        ? "Admin"
        : admin?.role ?? "—";

  return (
    <div className="dash-page">
      <div>
        <h1 className="dash-title">
          Account settings
        </h1>
        <p className="dash-sub">
          Update your sign-in details and appearance. Preferences follow you on
          other devices when you sign in.
        </p>
      </div>

      <div className="auth-glow-border max-w-lg space-y-4 rounded-xl bg-card/90 p-3 sm:p-5">
        <div>
          <p className="text-sm text-muted-foreground">Signed in as</p>
          <p className="mt-1 font-mono text-sm">{admin?.email ?? "—"}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Role: {roleLabel}
            {admin?.role === "sub_admin" &&
              typeof admin.config_slot_limit === "number" && (
                <>
                  {" "}
                  · Config slots: {admin.config_slots_used}/
                  {admin.config_slot_limit}
                </>
              )}
          </p>
        </div>

        <form onSubmit={(e) => void onCredentialsSubmit(e)} className="space-y-4">
          <div>
            <Label>Email & password</Label>
            <p className="mt-1 text-sm text-muted-foreground">
              Leave new email or password blank to keep the current value.
              Current password is always required.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="current-password">Current password</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              className="h-9"
              disabled={credBusy}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="new-email">New email</Label>
            <Input
              id="new-email"
              type="email"
              autoComplete="email"
              placeholder={admin?.email ?? "you@example.com"}
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
              className="h-9"
              disabled={credBusy}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="new-password">New password</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              className="h-9"
              disabled={credBusy}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirm-password">Confirm new password</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="h-9"
              disabled={credBusy}
            />
          </div>

          {credMessage && (
            <p className="font-mono text-xs text-cyan-600 dark:text-cyan-300">
              {credMessage}
            </p>
          )}
          {credError && (
            <p
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
            >
              {credError}
            </p>
          )}

          <Button
            type="submit"
            disabled={credBusy}
            className="brand-btn-gradient"
          >
            {credBusy ? "Saving…" : "Save credentials"}
          </Button>
        </form>

        <div className="space-y-3 border-t border-border/60 pt-6">
          <Label>Appearance</Label>
          <p className="text-sm text-muted-foreground">
            Choose light or dark. This updates for your account only.
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant={theme === "dark" ? "default" : "outline"}
              disabled={busy}
              onClick={() => void onThemeChange("dark")}
              className={
                theme === "dark" ? "brand-btn-gradient" : undefined
              }
            >
              Dark
            </Button>
            <Button
              type="button"
              variant={theme === "light" ? "default" : "outline"}
              disabled={busy}
              onClick={() => void onThemeChange("light")}
              className={
                theme === "light" ? "brand-btn-gradient" : undefined
              }
            >
              Light
            </Button>
          </div>
        </div>

        {message && (
          <p className="font-mono text-xs text-cyan-600 dark:text-cyan-300">
            {message}
          </p>
        )}
        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
