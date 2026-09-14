"use client";

import Link from "next/link";
import { useMemo, type ReactNode } from "react";

function Method({ children }: { children: string }) {
  const tone =
    children === "GET"
      ? "text-emerald-400"
      : children === "POST"
        ? "text-sky-400"
        : children === "PATCH"
          ? "text-amber-400"
          : children === "DELETE"
            ? "text-rose-400"
            : "text-muted-foreground";
  return (
    <span className={`font-mono text-xs font-semibold tracking-wide ${tone}`}>
      {children}
    </span>
  );
}

function Code({ children }: { children: string }) {
  return (
    <pre className="overflow-x-auto rounded-lg border border-border/70 bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-foreground/90 sm:text-xs">
      <code>{children}</code>
    </pre>
  );
}

function Inline({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-secondary/80 px-1 py-0.5 font-mono text-[11px] sm:text-xs">
      {children}
    </code>
  );
}

type Endpoint = {
  method: string;
  path: string;
  scope: string;
  summary: string;
  detail?: string;
  body?: string;
  query?: string;
  response?: string;
  example: string;
};

const ENDPOINTS: Endpoint[] = [
  {
    method: "GET",
    path: "/api/v1/health",
    scope: "none (any valid key)",
    summary: "Verify the key and list granted scopes.",
    response: `{
  "status": "ok",
  "key_id": "…",
  "scopes": ["configs:create", "analytics:read"],
  "owner_role": "admin"
}`,
    example: `curl -sS "$BASE/api/v1/health" \\
  -H "Authorization: Bearer $API_KEY"`,
  },
  {
    method: "POST",
    path: "/api/v1/configs",
    scope: "configs:create",
    summary: "Create a VPN client config. Returns metadata and the full .ovpn body.",
    detail:
      "Provide exactly one of expiry_days (7 | 30 | 90 | 365) or expires_at (ISO datetime). Status 201 on success.",
    body: `{
  "label": "laptop-alice",
  "expiry_days": 30
}`,
    response: `{
  "id": "…",
  "label": "laptop-alice",
  "client_name": "…",
  "status": "active",
  "expires_at": "…",
  "ovpn": "client\\ndev tun\\n…"
}`,
    example: `curl -sS -X POST "$BASE/api/v1/configs" \\
  -H "Authorization: Bearer $API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"label":"laptop-alice","expiry_days":30}'`,
  },
  {
    method: "DELETE",
    path: "/api/v1/configs/{config_id}",
    scope: "configs:revoke",
    summary: "Revoke an active config, or permanently delete an already-revoked one.",
    detail:
      "Active/expired → soft revoke (200 + config JSON). Already revoked → hard delete (204 empty).",
    example: `curl -sS -X DELETE "$BASE/api/v1/configs/$CONFIG_ID" \\
  -H "Authorization: Bearer $API_KEY"`,
  },
  {
    method: "GET",
    path: "/api/v1/configs/{config_id}/connection-logs",
    scope: "configs:logs",
    summary: "Connection events for one config (newest first, max 200).",
    response: `[
  {
    "id": "…",
    "at": "2026-09-10T02:00:00+00:00",
    "event": "connect",
    "client_name": "…",
    "wan_ip": "203.0.113.10",
    "vpn_ip": "10.8.0.5",
    "wan_logged": true
  }
]`,
    example: `curl -sS "$BASE/api/v1/configs/$CONFIG_ID/connection-logs" \\
  -H "Authorization: Bearer $API_KEY"`,
  },
  {
    method: "GET",
    path: "/api/v1/analytics/overview",
    scope: "analytics:read",
    summary: "Host metrics, client counts, bandwidth, and attack totals.",
    query: "hours=1–168 (default 24) · include_series=true|false (default true)",
    detail:
      "Extra throttle: at least 2.5s between calls per key (configurable on the key). Sub-admin keys only see their own configs’ stats.",
    example: `curl -sS "$BASE/api/v1/analytics/overview?hours=24&include_series=true" \\
  -H "Authorization: Bearer $API_KEY"`,
  },
  {
    method: "GET",
    path: "/api/v1/site-settings",
    scope: "settings:write + full-admin owner",
    summary: "Read server settings (secrets redacted).",
    detail: "Requires a key owned by a full admin with settings:write.",
    example: `curl -sS "$BASE/api/v1/site-settings" \\
  -H "Authorization: Bearer $API_KEY"`,
  },
  {
    method: "PATCH",
    path: "/api/v1/site-settings",
    scope: "settings:write + full-admin owner",
    summary: "Update traffic shaping and selected server knobs only.",
    body: `{
  "client_shape_enabled": true,
  "client_shape_down_mbit": 100,
  "client_shape_up_mbit": 50,
  "analytics_refresh_seconds": 5,
  "wan_ip_logging_enabled": true,
  "unique_wan_ip_limit": 3,
  "unique_wan_ip_window_hours": 24,
  "duplicate_cn_mode": false
}`,
    example: `curl -sS -X PATCH "$BASE/api/v1/site-settings" \\
  -H "Authorization: Bearer $API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"client_shape_down_mbit":100,"client_shape_up_mbit":50}'`,
  },
];

export function ApiDocs() {
  const base = useMemo(() => {
    if (typeof window === "undefined") return "https://admin.example.com";
    return window.location.origin;
  }, []);

  return (
    <div className="dash-page max-w-3xl space-y-8">
      <div>
        <h1 className="text-base font-semibold tracking-tight sm:text-lg">
          API documentation
        </h1>
        <p className="dash-sub">
          Machine API under <Inline>/api/v1</Inline>. Create keys in{" "}
          <Link
            href="/dashboard/settings"
            className="text-foreground underline-offset-2 hover:underline"
          >
            Account → API keys
          </Link>
          .
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Base URL</h2>
        <Code>{base}</Code>
        <p className="text-xs text-muted-foreground">
          All paths below are relative to this origin. Panel session JWTs are not
          accepted on <Inline>/api/v1/*</Inline> — use an API key.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Authentication</h2>
        <p className="text-sm text-muted-foreground">
          Keys look like <Inline>pk_live_&lt;prefix&gt;_&lt;secret&gt;</Inline>{" "}
          and are shown once at creation. Send either header:
        </p>
        <Code>{`Authorization: Bearer pk_live_…
# or
X-Api-Key: pk_live_…`}</Code>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Scopes</h2>
        <div className="overflow-x-auto rounded-xl border border-border/70">
          <table className="w-full min-w-[28rem] text-left text-sm">
            <thead className="border-b border-border/70 bg-secondary/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Scope</th>
                <th className="px-3 py-2 font-medium">Access</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {[
                ["configs:create", "POST /configs"],
                ["configs:revoke", "DELETE /configs/{id}"],
                ["configs:logs", "GET …/connection-logs"],
                ["analytics:read", "GET /analytics/overview"],
                [
                  "settings:write",
                  "GET/PATCH /site-settings (full-admin keys only)",
                ],
              ].map(([scope, access]) => (
                <tr key={scope}>
                  <td className="px-3 py-2 font-mono text-xs">{scope}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {access}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">
          Missing scope → <Inline>403</Inline>. Keys inherit the owner’s
          role and ownership (sub-admins only act on their configs).
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Rate limits</h2>
        <ul className="list-inside list-disc space-y-1 text-sm text-muted-foreground">
          <li>
            Per-key sliding window (default <Inline>60</Inline>/min, set when
            creating the key) → <Inline>429</Inline> with{" "}
            <Inline>Retry-After</Inline>
          </li>
          <li>
            Analytics overview also enforces a minimum interval (default{" "}
            <Inline>2.5s</Inline>)
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">
          Quick start
        </h2>
        <Code>{`export BASE="${base}"
export API_KEY="pk_live_…"

curl -sS "$BASE/api/v1/health" \\
  -H "Authorization: Bearer $API_KEY"`}</Code>
      </section>

      <section className="space-y-6">
        <h2 className="text-sm font-semibold tracking-tight">Endpoints</h2>
        {ENDPOINTS.map((ep) => (
          <article
            key={`${ep.method}-${ep.path}`}
            className="space-y-3 rounded-xl border border-border/70 bg-card/40 p-3 sm:p-4"
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Method>{ep.method}</Method>
              <span className="font-mono text-xs sm:text-sm">{ep.path}</span>
            </div>
            <p className="text-sm text-muted-foreground">{ep.summary}</p>
            <p className="text-xs text-muted-foreground">
              Scope: <Inline>{ep.scope}</Inline>
            </p>
            {ep.detail ? (
              <p className="text-xs text-muted-foreground">{ep.detail}</p>
            ) : null}
            {ep.query ? (
              <div className="space-y-1">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Query
                </p>
                <p className="font-mono text-xs text-foreground/90">{ep.query}</p>
              </div>
            ) : null}
            {ep.body ? (
              <div className="space-y-1.5">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Body
                </p>
                <Code>{ep.body}</Code>
              </div>
            ) : null}
            {ep.response ? (
              <div className="space-y-1.5">
                <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Response
                </p>
                <Code>{ep.response}</Code>
              </div>
            ) : null}
            <div className="space-y-1.5">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Example
              </p>
              <Code>{ep.example}</Code>
            </div>
          </article>
        ))}
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold tracking-tight">Errors</h2>
        <div className="overflow-x-auto rounded-xl border border-border/70">
          <table className="w-full min-w-[24rem] text-left text-sm">
            <thead className="border-b border-border/70 bg-secondary/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Meaning</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60 text-xs text-muted-foreground">
              <tr>
                <td className="px-3 py-2 font-mono text-foreground">401</td>
                <td className="px-3 py-2">Missing or invalid API key</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono text-foreground">403</td>
                <td className="px-3 py-2">
                  Missing scope, locked owner, or full-admin required
                </td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono text-foreground">404</td>
                <td className="px-3 py-2">Config not found / not owned</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono text-foreground">422</td>
                <td className="px-3 py-2">Validation error</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono text-foreground">429</td>
                <td className="px-3 py-2">Rate limit — check Retry-After</td>
              </tr>
              <tr>
                <td className="px-3 py-2 font-mono text-foreground">502/503</td>
                <td className="px-3 py-2">Upstream / database unavailable</td>
              </tr>
            </tbody>
          </table>
        </div>
        <Code>{`{"detail": "API key missing scope: configs:create"}`}</Code>
      </section>
    </div>
  );
}
