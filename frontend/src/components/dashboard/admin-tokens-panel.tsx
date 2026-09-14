"use client";

import { Copy, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  PAGE_SIZE,
  PaginationTabs,
  slicePage,
} from "@/components/dashboard/pagination-tabs";
import {
  ApiError,
  createRegistrationToken,
  deleteRegistrationToken,
  listRegistrationTokens,
  type AdminRole,
  type RegistrationToken,
} from "@/lib/api";
import { copyText } from "@/lib/clipboard";

function formatDate(iso: string): string {
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

function roleLabel(role: string): string {
  if (role === "sub_admin") return "Sub-admin";
  if (role === "admin") return "Admin";
  return role;
}

export function AdminTokensPanel() {
  const [tokens, setTokens] = useState<RegistrationToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [role, setRole] = useState<AdminRole>("sub_admin");
  const [slotLimit, setSlotLimit] = useState("5");
  const [note, setNote] = useState("");
  const [expiresHours, setExpiresHours] = useState("24");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [createdToken, setCreatedToken] = useState<RegistrationToken | null>(
    null,
  );
  const [copyMessage, setCopyMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [page, setPage] = useState(1);

  const pageTokens = slicePage(tokens, page, PAGE_SIZE);

  useEffect(() => {
    const maxPage = Math.max(1, Math.ceil(tokens.length / PAGE_SIZE));
    if (page > maxPage) setPage(maxPage);
  }, [tokens.length, page]);

  const refresh = useCallback(async () => {
    setListError(null);
    try {
      const data = await listRegistrationTokens();
      setTokens(data);
    } catch (err) {
      setListError(
        err instanceof ApiError
          ? err.message
          : "Could not load registration tokens.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setCreatedToken(null);
    setCopyMessage(null);

    const hours = Number(expiresHours);
    if (!Number.isFinite(hours) || hours < 1) {
      setFormError("Token lifetime must be at least 1 hour.");
      return;
    }

    let slots: number | undefined;
    if (role === "sub_admin") {
      slots = Number(slotLimit);
      if (!Number.isFinite(slots) || slots < 1) {
        setFormError("Sub-admin tokens need a config slot limit of at least 1.");
        return;
      }
    }

    setCreating(true);
    try {
      const token = await createRegistrationToken({
        role,
        expires_in_hours: Math.floor(hours),
        ...(role === "sub_admin" ? { config_slot_limit: Math.floor(slots!) } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      });
      setCreatedToken(token);
      setTokens((prev) => [token, ...prev.filter((t) => t.id !== token.id)]);
      setNote("");
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? err.message
          : "Could not create registration token.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function onCopy(value: string) {
    const ok = await copyText(value);
    setCopyMessage(
      ok
        ? "Token copied to clipboard."
        : "Could not copy — select the token manually.",
    );
  }

  async function onDelete(token: RegistrationToken) {
    setActionError(null);
    try {
      await deleteRegistrationToken(token.id);
      setTokens((prev) => prev.filter((t) => t.id !== token.id));
      if (createdToken?.id === token.id) setCreatedToken(null);
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not delete this token.",
      );
    }
  }

  return (
    <div className="dash-page">
      <div>
        <h2 className="text-base font-semibold tracking-tight sm:text-lg">
          Registration tokens
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Generate one-time registration tokens for new admin or sub-admin
          accounts. Sub-admins can only manage their own VPN configs up to the
          slot limit you set.
        </p>
      </div>

      <form
        onSubmit={(e) => void onCreate(e)}
        className="auth-glow-border max-w-lg space-y-3 rounded-xl bg-card/90 p-3 sm:p-4"
      >
        <div>
          <Label>New registration token</Label>
          <p className="mt-1 text-sm text-muted-foreground">
            Share the token once. It is consumed when they register.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="token-role">Account role</Label>
          <select
            id="token-role"
            value={role}
            onChange={(e) => setRole(e.target.value as AdminRole)}
            className="flex h-9 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
            disabled={creating}
          >
            <option value="sub_admin">Sub-admin</option>
            <option value="admin">Admin (full access)</option>
          </select>
        </div>

        {role === "sub_admin" && (
          <div className="space-y-2">
            <Label htmlFor="slot-limit">VPN config slots</Label>
            <Input
              id="slot-limit"
              type="number"
              min={1}
              max={10000}
              value={slotLimit}
              onChange={(e) => setSlotLimit(e.target.value)}
              className="h-10"
              disabled={creating}
            />
            <p className="text-xs text-muted-foreground">
              Max non-revoked configs this sub-admin can hold. Revoking frees a
              slot.
            </p>
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="token-note">Note (optional)</Label>
          <Input
            id="token-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Partner — Acme"
            className="h-10"
            disabled={creating}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="token-ttl">Expires in (hours)</Label>
          <Input
            id="token-ttl"
            type="number"
            min={1}
            max={720}
            value={expiresHours}
            onChange={(e) => setExpiresHours(e.target.value)}
            className="h-10"
            disabled={creating}
          />
        </div>

        {formError && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {formError}
          </p>
        )}

        {createdToken && (
          <div className="space-y-2 rounded-lg border border-border/80 bg-secondary/30 p-3">
            <p className="text-sm font-medium">Token created</p>
            <p className="break-all font-mono text-xs">{createdToken.token}</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => void onCopy(createdToken.token)}
            >
              <Copy />
              Copy token
            </Button>
            {copyMessage && (
              <p className="font-mono text-xs text-cyan-600 dark:text-cyan-300">
                {copyMessage}
              </p>
            )}
          </div>
        )}

        <Button
          type="submit"
          disabled={creating}
          className="brand-btn-gradient"
        >
          {creating ? "Generating…" : "Generate token"}
        </Button>
      </form>

      {(listError || actionError || copyMessage) && (
        <p
          role={listError || actionError ? "alert" : undefined}
          className={
            listError || actionError
              ? "rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
              : "font-mono text-xs text-cyan-600 dark:text-cyan-300"
          }
        >
          {listError || actionError || copyMessage}
        </p>
      )}

      {/* Mobile cards */}
      <div className="space-y-2 md:hidden">
        {loading && (
          <p className="py-5 text-center font-mono text-sm text-muted-foreground">
            Loading tokens…
          </p>
        )}
        {!loading && tokens.length === 0 && (
          <div className="dash-empty">
            No registration tokens yet.
          </div>
        )}
        {!loading &&
          pageTokens.map((token) => {
            const expired = new Date(token.expires_at) <= new Date();
            const status = token.used
              ? "Used"
              : expired
                ? "Expired"
                : "Unused";
            return (
              <article
                key={token.id}
                className="dash-card"
              >
                <div className="min-w-0">
                  <p className="break-all font-mono text-xs">{token.token}</p>
                  {token.note && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {token.note}
                    </p>
                  )}
                </div>
                <dl className="grid grid-cols-2 gap-2 font-mono text-[11px] text-muted-foreground">
                  <div>
                    <dt className="text-muted-foreground/80">Role</dt>
                    <dd className="mt-0.5 text-foreground/90">
                      {roleLabel(token.role)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground/80">Slots</dt>
                    <dd className="mt-0.5">{token.config_slot_limit ?? "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground/80">Status</dt>
                    <dd className="mt-0.5">{status}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground/80">Expires</dt>
                    <dd className="mt-0.5">{formatDate(token.expires_at)}</dd>
                  </div>
                </dl>
                <div className="flex flex-wrap gap-2">
                  {!token.used && !expired && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => void onCopy(token.token)}
                    >
                      <Copy />
                      Copy
                    </Button>
                  )}
                  {!token.used && (
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      onClick={() => void onDelete(token)}
                    >
                      <Trash2 />
                      Delete
                    </Button>
                  )}
                </div>
              </article>
            );
          })}
        <PaginationTabs
          page={page}
          totalItems={tokens.length}
          onPageChange={setPage}
          className="rounded-xl border border-border/60 bg-card/50"
        />
      </div>

      {/* Desktop table */}
      <div className="auth-glow-border hidden overflow-hidden rounded-xl bg-card/90 md:block">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-border bg-secondary/40">
              <tr>
                <th className="px-4 py-3 font-medium">Token</th>
                <th className="px-4 py-3 font-medium">Role</th>
                <th className="px-4 py-3 font-medium">Slots</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Expires</th>
                <th className="px-4 py-3 font-medium text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-10 text-center font-mono text-sm text-muted-foreground"
                  >
                    Loading tokens…
                  </td>
                </tr>
              )}
              {!loading && tokens.length === 0 && (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-10 text-center text-sm text-muted-foreground"
                  >
                    No registration tokens yet.
                  </td>
                </tr>
              )}
              {!loading &&
                pageTokens.map((token) => {
                  const expired = new Date(token.expires_at) <= new Date();
                  const status = token.used
                    ? "Used"
                    : expired
                      ? "Expired"
                      : "Unused";
                  return (
                    <tr
                      key={token.id}
                      className="border-b border-border/60 last:border-0"
                    >
                      <td className="px-4 py-3">
                        <div className="max-w-[220px] truncate font-mono text-xs">
                          {token.token}
                        </div>
                        {token.note && (
                          <div className="mt-0.5 text-xs text-muted-foreground">
                            {token.note}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">{roleLabel(token.role)}</td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {token.config_slot_limit ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-xs">{status}</td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {formatDate(token.expires_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          {!token.used && !expired && (
                            <Button
                              type="button"
                              variant="outline"
                              size="sm"
                              onClick={() => void onCopy(token.token)}
                              title="Copy token"
                            >
                              <Copy />
                              Copy
                            </Button>
                          )}
                          {!token.used && (
                            <Button
                              type="button"
                              variant="destructive"
                              size="sm"
                              onClick={() => void onDelete(token)}
                              title="Delete unused token"
                            >
                              <Trash2 />
                              Delete
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
        <PaginationTabs
          page={page}
          totalItems={tokens.length}
          onPageChange={setPage}
        />
      </div>
    </div>
  );
}
