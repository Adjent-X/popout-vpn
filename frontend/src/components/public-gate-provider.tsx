"use client";

import { useEffect, useState } from "react";

import { useBrand } from "@/components/brand-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  syncPublicGateState,
  unlockPublicGate,
} from "@/lib/api";

/**
 * Non-dismissible password gate for the public Cloudflare site.
 * Opaque full-screen when locked — never shows the app underneath.
 */
export function PublicGateProvider({ children }: { children: React.ReactNode }) {
  const { config, refresh } = useBrand();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const gateEnabled = config.public_gate_enabled === true;
  const unlocked = config.public_gate_unlocked !== false;
  const locked = gateEnabled && !unlocked;

  useEffect(() => {
    syncPublicGateState(
      Boolean(config.public_gate_enabled),
      config.public_gate_unlocked !== false,
    );
  }, [config.public_gate_enabled, config.public_gate_unlocked]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!password.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await unlockPublicGate(password);
      setPassword("");
      await refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not unlock. Check the password and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (locked) {
    return (
      <div className="auth-grid flex min-h-screen items-center justify-center p-4">
        <form
          onSubmit={(e) => void onSubmit(e)}
          className="auth-glow-border w-full max-w-sm space-y-4 rounded-xl bg-card/95 p-5"
        >
          <div>
            <h1 className="text-base font-semibold tracking-tight">
              Site password
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Enter the admin gate password to continue. There is no username.
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="public-gate-password">Password</Label>
            <Input
              id="public-gate-password"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 font-mono"
              disabled={busy}
              placeholder="Gate password"
            />
          </div>
          {error && (
            <p
              role="alert"
              className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
            >
              {error}
            </p>
          )}
          <Button
            type="submit"
            disabled={busy || !password.trim()}
            className="brand-btn-gradient h-10 w-full"
          >
            {busy ? "Unlocking…" : "Unlock"}
          </Button>
        </form>
      </div>
    );
  }

  return <>{children}</>;
}
