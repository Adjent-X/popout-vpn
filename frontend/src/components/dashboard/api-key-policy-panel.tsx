"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  fetchApiKeyPolicy,
  updateApiKeyPolicy,
  type ApiKeyPolicy,
  type ApiScope,
} from "@/lib/api";

const ALL_SCOPES: ApiScope[] = [
  "configs:create",
  "configs:revoke",
  "configs:logs",
  "analytics:read",
  "settings:write",
];

const SCOPE_LABEL: Record<ApiScope, string> = {
  "configs:create": "Create configs",
  "configs:revoke": "Revoke configs",
  "configs:logs": "Connection logs",
  "analytics:read": "Server analytics",
  "settings:write": "Shaping & server settings",
};

export function ApiKeyPolicyPanel() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [policy, setPolicy] = useState<ApiKeyPolicy | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setPolicy(await fetchApiKeyPolicy());
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not load API key policy.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function toggleScope(
    field: "sub_admin_scopes" | "admin_scopes",
    scope: ApiScope,
  ) {
    setPolicy((prev) => {
      if (!prev) return prev;
      const list = prev[field];
      const next = list.includes(scope)
        ? list.filter((s) => s !== scope)
        : [...list, scope];
      return { ...prev, [field]: next };
    });
  }

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!policy) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await updateApiKeyPolicy(policy);
      setPolicy(updated);
      setMessage("API key policy saved.");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not save API key policy.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading || !policy) {
    return (
      <div className="auth-glow-border rounded-xl bg-card/90 p-4">
        <p className="font-mono text-sm text-muted-foreground">
          {error ?? "Loading API key policy…"}
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={(e) => void onSave(e)}
      className="auth-glow-border space-y-4 rounded-xl bg-card/90 p-3 sm:p-5"
    >
      <div>
        <h2 className="text-base font-semibold tracking-tight sm:text-lg">
          REST API key policy
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Controls which scopes each role may put on keys, default rate limits,
          and the analytics poll floor (minimum 2.5s). Machine clients use{" "}
          <span className="font-mono text-[11px]">/api/v1/*</span> with Bearer
          or <span className="font-mono text-[11px]">X-Api-Key</span>.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {(
          [
            ["sub_admin_scopes", "Sub-admin scopes"],
            ["admin_scopes", "Full-admin scopes"],
          ] as const
        ).map(([field, title]) => (
          <div key={field} className="space-y-2">
            <Label>{title}</Label>
            <div className="space-y-1.5 rounded-lg border border-border/60 p-3">
              {ALL_SCOPES.map((scope) => {
                const blocked =
                  field === "sub_admin_scopes" && scope === "settings:write";
                return (
                  <label
                    key={scope}
                    className={`flex items-start gap-2 text-sm ${
                      blocked ? "opacity-50" : ""
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 size-4 rounded border-input"
                      checked={policy[field].includes(scope)}
                      disabled={blocked || saving}
                      onChange={() => {
                        if (!blocked) toggleScope(field, scope);
                      }}
                    />
                    <span>
                      <span className="font-mono text-xs">{scope}</span>
                      <span className="mt-0.5 block text-xs text-muted-foreground">
                        {SCOPE_LABEL[scope]}
                        {blocked ? " (full-admin only)" : ""}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor="api-def-rate">Default req/min</Label>
          <Input
            id="api-def-rate"
            type="number"
            min={1}
            value={policy.default_rate_limit_per_minute}
            onChange={(e) =>
              setPolicy({
                ...policy,
                default_rate_limit_per_minute: Number(e.target.value) || 1,
              })
            }
            className="h-9 font-mono text-sm"
            disabled={saving}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="api-max-rate">Max req/min</Label>
          <Input
            id="api-max-rate"
            type="number"
            min={1}
            value={policy.max_rate_limit_per_minute}
            onChange={(e) =>
              setPolicy({
                ...policy,
                max_rate_limit_per_minute: Number(e.target.value) || 1,
              })
            }
            className="h-9 font-mono text-sm"
            disabled={saving}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="api-analytics-floor">Analytics floor (s)</Label>
          <Input
            id="api-analytics-floor"
            type="number"
            min={2.5}
            step={0.5}
            value={policy.analytics_min_interval_seconds}
            onChange={(e) =>
              setPolicy({
                ...policy,
                analytics_min_interval_seconds: Math.max(
                  2.5,
                  Number(e.target.value) || 2.5,
                ),
              })
            }
            className="h-9 font-mono text-sm"
            disabled={saving}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="api-max-keys">Max keys / admin</Label>
          <Input
            id="api-max-keys"
            type="number"
            min={1}
            value={policy.max_keys_per_admin}
            onChange={(e) =>
              setPolicy({
                ...policy,
                max_keys_per_admin: Number(e.target.value) || 1,
              })
            }
            className="h-9 font-mono text-sm"
            disabled={saving}
          />
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

      <Button type="submit" disabled={saving} className="brand-btn-gradient h-9">
        {saving ? "Saving…" : "Save API key policy"}
      </Button>
    </form>
  );
}
