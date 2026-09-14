"use client";

import { Copy, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  PAGE_SIZE,
  PaginationTabs,
  slicePage,
} from "@/components/dashboard/pagination-tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  createApiKey,
  deleteApiKey,
  fetchMyApiScopes,
  listApiKeys,
  type ApiKey,
  type ApiScope,
  type CreateApiKeyResponse,
} from "@/lib/api";
import { copyText } from "@/lib/clipboard";

const SCOPE_HELP: Record<string, string> = {
  "configs:create": "Create VPN configs",
  "configs:revoke": "Revoke / delete configs",
  "configs:logs": "Read connection logs",
  "analytics:read": "Server analytics (≥2.5s)",
  "settings:write": "Shaping & server settings",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function ApiKeysPanel() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [allowedScopes, setAllowedScopes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiScope[]>([]);
  const [rateLimit, setRateLimit] = useState("60");
  const [analyticsIv, setAnalyticsIv] = useState("2.5");
  const [expiresDays, setExpiresDays] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreateApiKeyResponse | null>(null);
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const pageKeys = slicePage(keys, page, PAGE_SIZE);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(keys.length / PAGE_SIZE));
    if (page > maxPage) setPage(maxPage);
  }, [keys.length, page]);

  const refresh = useCallback(async () => {
    setListError(null);
    try {
      const [rows, allowed] = await Promise.all([
        listApiKeys(),
        fetchMyApiScopes(),
      ]);
      setKeys(rows);
      setAllowedScopes(allowed);
      setScopes((prev) => {
        const next = prev.filter((s) => allowed.includes(s));
        if (next.length) return next;
        return allowed.includes("configs:create")
          ? (["configs:create"] as ApiScope[])
          : (allowed.slice(0, 1) as ApiScope[]);
      });
    } catch (err) {
      setListError(
        err instanceof ApiError ? err.message : "Could not load API keys.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function toggleScope(scope: ApiScope) {
    setScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || scopes.length === 0) {
      setFormError("Name and at least one scope are required.");
      return;
    }
    setCreating(true);
    setFormError(null);
    setCreated(null);
    try {
      const body: Parameters<typeof createApiKey>[0] = {
        name: name.trim(),
        scopes,
      };
      const rate = Number(rateLimit);
      if (Number.isFinite(rate) && rate > 0) body.rate_limit_per_minute = rate;
      const iv = Number(analyticsIv);
      if (Number.isFinite(iv) && iv >= 2.5) {
        body.analytics_min_interval_seconds = iv;
      }
      const days = Number(expiresDays);
      if (expiresDays.trim() && Number.isFinite(days) && days > 0) {
        body.expires_in_days = days;
      }
      const row = await createApiKey(body);
      setCreated(row);
      setName("");
      await refresh();
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : "Could not create API key.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function onCopy(text: string) {
    const ok = await copyText(text);
    setCopyMessage(ok ? "Copied." : "Copy failed.");
    setTimeout(() => setCopyMessage(null), 2000);
  }

  async function onDelete(id: string) {
    setActionError(null);
    try {
      await deleteApiKey(id);
      setKeys((prev) => prev.filter((k) => k.id !== id));
      if (created?.id === id) setCreated(null);
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not delete API key.",
      );
    }
  }

  return (
    <div className="dash-page">
      <div>
        <h2 className="text-base font-semibold tracking-tight sm:text-lg">
          API keys
        </h2>
        <p className="dash-sub">
          Machine access to{" "}
          <span className="font-mono text-[11px]">/api/v1/*</span>. Keys are
          shown once at creation — store them securely. See{" "}
          <Link
            href="/dashboard/docs"
            className="text-foreground underline-offset-2 hover:underline"
          >
            API docs
          </Link>
          .
        </p>
      </div>

      <form
        onSubmit={(e) => void onCreate(e)}
        className="auth-glow-border max-w-lg space-y-3 rounded-xl bg-card/90 p-3 sm:p-4"
      >
        <div className="space-y-2">
          <Label htmlFor="api-key-name">Name</Label>
          <Input
            id="api-key-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-9"
            placeholder="CI bot / monitoring"
            disabled={creating}
          />
        </div>
        <div className="space-y-2">
          <Label>Scopes</Label>
          <div className="grid gap-1.5">
            {allowedScopes.map((scope) => (
              <label
                key={scope}
                className="flex items-start gap-2 text-sm"
              >
                <input
                  type="checkbox"
                  className="mt-1 size-4 rounded border-input"
                  checked={scopes.includes(scope as ApiScope)}
                  onChange={() => toggleScope(scope as ApiScope)}
                  disabled={creating}
                />
                <span>
                  <span className="font-mono text-xs">{scope}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {SCOPE_HELP[scope] ?? scope}
                  </span>
                </span>
              </label>
            ))}
            {allowedScopes.length === 0 && (
              <p className="text-xs text-muted-foreground">
                No scopes available for your role. Ask a full admin to update
                API key policy.
              </p>
            )}
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="space-y-1.5">
            <Label htmlFor="api-rate">Req / min</Label>
            <Input
              id="api-rate"
              type="number"
              min={1}
              value={rateLimit}
              onChange={(e) => setRateLimit(e.target.value)}
              className="h-9 font-mono text-sm"
              disabled={creating}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="api-analytics-iv">Analytics min (s)</Label>
            <Input
              id="api-analytics-iv"
              type="number"
              min={2.5}
              step={0.5}
              value={analyticsIv}
              onChange={(e) => setAnalyticsIv(e.target.value)}
              className="h-9 font-mono text-sm"
              disabled={creating}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="api-expires">Expires (days)</Label>
            <Input
              id="api-expires"
              type="number"
              min={1}
              value={expiresDays}
              onChange={(e) => setExpiresDays(e.target.value)}
              className="h-9 font-mono text-sm"
              placeholder="Never"
              disabled={creating}
            />
          </div>
        </div>
        {formError && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {formError}
          </p>
        )}
        <Button
          type="submit"
          disabled={creating || allowedScopes.length === 0}
          className="brand-btn-gradient h-9"
        >
          {creating ? "Creating…" : "Create API key"}
        </Button>
      </form>

      {created && (
        <div className="auth-glow-border max-w-lg space-y-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3">
          <p className="text-sm font-medium">Copy this key now</p>
          <p className="font-mono text-[11px] break-all text-muted-foreground">
            {created.api_key}
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void onCopy(created.api_key)}
          >
            <Copy className="mr-1.5 size-3.5" />
            Copy
          </Button>
          {copyMessage && (
            <p className="font-mono text-[11px] text-muted-foreground">
              {copyMessage}
            </p>
          )}
        </div>
      )}

      {(listError || actionError) && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
        >
          {listError || actionError}
        </p>
      )}

      <div className="space-y-2 md:hidden">
        {loading && (
          <p className="py-5 text-center font-mono text-sm text-muted-foreground">
            Loading keys…
          </p>
        )}
        {!loading && keys.length === 0 && (
          <div className="dash-empty">No API keys yet.</div>
        )}
        {pageKeys.map((key) => (
          <article key={key.id} className="dash-card">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-medium">{key.name}</p>
                <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                  pk_live_{key.key_prefix}_…
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="text-destructive"
                onClick={() => void onDelete(key.id)}
              >
                <Trash2 className="size-3.5" />
              </Button>
            </div>
            <p className="font-mono text-[10px] text-muted-foreground">
              {key.scopes.join(" · ")}
            </p>
            <p className="font-mono text-[10px] text-muted-foreground">
              {key.rate_limit_per_minute}/min · analytics ≥
              {key.analytics_min_interval_seconds}s · created{" "}
              {formatDate(key.created_at)}
            </p>
          </article>
        ))}
      </div>

      <div className="auth-glow-border hidden overflow-hidden rounded-xl bg-card/90 md:block">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-border bg-secondary/40">
            <tr>
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Prefix</th>
              <th className="px-3 py-2 font-medium">Scopes</th>
              <th className="px-3 py-2 font-medium">Limits</th>
              <th className="px-3 py-2 font-medium">Created</th>
              <th className="w-12 px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-6 text-center font-mono text-sm text-muted-foreground"
                >
                  Loading…
                </td>
              </tr>
            )}
            {!loading && keys.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-6 text-center text-sm text-muted-foreground"
                >
                  No API keys yet.
                </td>
              </tr>
            )}
            {pageKeys.map((key) => (
              <tr key={key.id} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-2 font-medium">{key.name}</td>
                <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                  {key.key_prefix}
                </td>
                <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
                  {key.scopes.join(", ")}
                </td>
                <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
                  {key.rate_limit_per_minute}/min · ≥
                  {key.analytics_min_interval_seconds}s
                </td>
                <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
                  {formatDate(key.created_at)}
                </td>
                <td className="px-3 py-2 text-right">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="text-destructive"
                    onClick={() => void onDelete(key.id)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <PaginationTabs
          page={page}
          totalItems={keys.length}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}
