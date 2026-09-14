"use client";

import { Lock, LockOpen, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PrivateWanIp } from "@/components/dashboard/private-wan-ip";
import {
  ApiError,
  deleteAdminAccount,
  listAdmins,
  updateAdminAccount,
  type AdminPublic,
} from "@/lib/api";
import { getStoredAdmin } from "@/lib/auth";
import { cn } from "@/lib/utils";

function formatWhen(iso: string | null | undefined): string {
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

function roleLabel(role: string): string {
  if (role === "sub_admin") return "Sub-admin";
  if (role === "admin") return "Full admin";
  return role;
}

export function AdminAccountsPanel() {
  const me = getStoredAdmin();
  const [accounts, setAccounts] = useState<AdminPublic[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editEmail, setEditEmail] = useState("");
  const [editPassword, setEditPassword] = useState("");
  const [editSlots, setEditSlots] = useState("");

  const refresh = useCallback(async () => {
    setListError(null);
    try {
      const data = await listAdmins();
      setAccounts(data);
    } catch (err) {
      setListError(
        err instanceof ApiError
          ? err.message
          : "Could not load admin accounts.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function startEdit(account: AdminPublic) {
    setEditingId(account.id);
    setEditEmail(account.email);
    setEditPassword("");
    setEditSlots(
      account.config_slot_limit != null
        ? String(account.config_slot_limit)
        : "",
    );
    setActionError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditEmail("");
    setEditPassword("");
    setEditSlots("");
  }

  async function saveEdit(account: AdminPublic) {
    setBusyId(account.id);
    setActionError(null);
    try {
      const body: Parameters<typeof updateAdminAccount>[1] = {};
      if (editEmail.trim().toLowerCase() !== account.email.toLowerCase()) {
        body.email = editEmail.trim();
      }
      if (editPassword.trim()) {
        body.password = editPassword.trim();
      }
      if (account.role === "sub_admin") {
        const slots = Number(editSlots);
        if (!Number.isInteger(slots) || slots < 1) {
          setActionError("Sub-admins need a slot limit of at least 1.");
          return;
        }
        if (slots !== account.config_slot_limit) {
          body.config_slot_limit = slots;
        }
      } else if (editSlots.trim() === "") {
        if (account.config_slot_limit != null) {
          body.clear_slot_limit = true;
        }
      } else {
        const slots = Number(editSlots);
        if (!Number.isInteger(slots) || slots < 1) {
          setActionError("Slot limit must be a positive integer (or blank).");
          return;
        }
        if (slots !== account.config_slot_limit) {
          body.config_slot_limit = slots;
        }
      }

      if (Object.keys(body).length === 0) {
        cancelEdit();
        return;
      }

      const updated = await updateAdminAccount(account.id, body);
      setAccounts((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)),
      );
      cancelEdit();
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not update account.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function toggleLock(account: AdminPublic) {
    if (account.id === me?.id) return;
    setBusyId(account.id);
    setActionError(null);
    try {
      const updated = await updateAdminAccount(account.id, {
        locked: !account.locked,
      });
      setAccounts((prev) =>
        prev.map((a) => (a.id === updated.id ? updated : a)),
      );
    } catch (err) {
      setActionError(
        err instanceof ApiError
          ? err.message
          : "Could not update lock state.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function onDelete(account: AdminPublic) {
    if (account.id === me?.id) return;
    const ok = window.confirm(
      `Delete account ${account.email}? This cannot be undone.`,
    );
    if (!ok) return;
    setBusyId(account.id);
    setActionError(null);
    try {
      await deleteAdminAccount(account.id);
      setAccounts((prev) => prev.filter((a) => a.id !== account.id));
      if (editingId === account.id) cancelEdit();
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "Could not delete account.",
      );
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold tracking-tight sm:text-lg">Accounts</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage all admin and sub-admin accounts — email, password, slots,
          lock, and delete.
        </p>
      </div>

      {(listError || actionError) && (
        <p
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
        >
          {listError || actionError}
        </p>
      )}

      {/* Mobile cards */}
      <div className="space-y-2 md:hidden">
        {loading && (
          <p className="py-5 text-center font-mono text-sm text-muted-foreground">
            Loading accounts…
          </p>
        )}
        {!loading && accounts.length === 0 && (
          <div className="dash-empty">
            No accounts found.
          </div>
        )}
        {!loading &&
          accounts.map((account) => {
            const isSelf = account.id === me?.id;
            const editing = editingId === account.id;
            const busy = busyId === account.id;
            return (
              <article
                key={account.id}
                className="dash-card"
              >
                {editing ? (
                  <div className="space-y-3">
                    <div className="space-y-1">
                      <Label
                        htmlFor={`email-m-${account.id}`}
                        className="text-[11px] text-muted-foreground"
                      >
                        Email
                      </Label>
                      <Input
                        id={`email-m-${account.id}`}
                        value={editEmail}
                        onChange={(e) => setEditEmail(e.target.value)}
                        className="h-9 font-mono text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label
                        htmlFor={`pw-m-${account.id}`}
                        className="text-[11px] text-muted-foreground"
                      >
                        New password (optional)
                      </Label>
                      <Input
                        id={`pw-m-${account.id}`}
                        type="password"
                        value={editPassword}
                        onChange={(e) => setEditPassword(e.target.value)}
                        placeholder="Leave blank to keep"
                        className="h-9 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label
                        htmlFor={`slots-m-${account.id}`}
                        className="text-[11px] text-muted-foreground"
                      >
                        Slot limit
                      </Label>
                      <Input
                        id={`slots-m-${account.id}`}
                        value={editSlots}
                        onChange={(e) => setEditSlots(e.target.value)}
                        placeholder={
                          account.role === "admin" ? "unlimited" : "5"
                        }
                        className="h-9 font-mono text-xs"
                      />
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        className="brand-btn-gradient"
                        disabled={busy}
                        onClick={() => void saveEdit(account)}
                      >
                        Save
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={cancelEdit}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium">{account.email}</p>
                        <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                          {roleLabel(String(account.role))}
                          {isSelf ? " · you" : ""}
                        </p>
                      </div>
                      <span
                        className={cn(
                          "shrink-0 inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide",
                          account.locked
                            ? "border-destructive/40 bg-destructive/10 text-destructive"
                            : "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                        )}
                      >
                        {account.locked ? "Locked" : "Active"}
                      </span>
                    </div>
                    <dl className="grid grid-cols-2 gap-2 font-mono text-[11px] text-muted-foreground">
                      <div>
                        <dt className="text-muted-foreground/80">Slots</dt>
                        <dd className="mt-0.5">
                          {account.config_slot_limit == null
                            ? `${account.config_slots_used ?? 0} / ∞`
                            : `${account.config_slots_used ?? 0} / ${account.config_slot_limit}`}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-muted-foreground/80">Last login</dt>
                        <dd className="mt-0.5">
                          {formatWhen(account.last_login_at)}
                        </dd>
                        <dd className="text-muted-foreground/80">
                          <PrivateWanIp ip={account.last_login_ip} />
                        </dd>
                      </div>
                    </dl>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => startEdit(account)}
                      >
                        Edit
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={busy || isSelf}
                        onClick={() => void toggleLock(account)}
                      >
                        {account.locked ? (
                          <LockOpen className="size-3.5" />
                        ) : (
                          <Lock className="size-3.5" />
                        )}
                        {account.locked ? "Unlock" : "Lock"}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        disabled={busy || isSelf}
                        onClick={() => void onDelete(account)}
                      >
                        <Trash2 className="size-3.5" />
                        Delete
                      </Button>
                    </div>
                  </>
                )}
              </article>
            );
          })}
      </div>

      {/* Desktop table */}
      <div className="auth-glow-border hidden overflow-hidden rounded-xl bg-card/90 md:block">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="border-b border-border bg-secondary/40">
              <tr>
                <th className="px-4 py-3 font-medium">Email / role</th>
                <th className="px-4 py-3 font-medium">Slots</th>
                <th className="px-4 py-3 font-medium">Last login</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 text-right font-medium">Manage</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center font-mono text-sm text-muted-foreground"
                  >
                    Loading accounts…
                  </td>
                </tr>
              )}
              {!loading && accounts.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    className="px-4 py-10 text-center text-sm text-muted-foreground"
                  >
                    No accounts found.
                  </td>
                </tr>
              )}
              {!loading &&
                accounts.map((account) => {
                  const isSelf = account.id === me?.id;
                  const editing = editingId === account.id;
                  const busy = busyId === account.id;
                  return (
                    <tr
                      key={account.id}
                      className="border-b border-border/60 last:border-0 align-top"
                    >
                      <td className="px-4 py-3">
                        {editing ? (
                          <div className="space-y-2 max-w-xs">
                            <div className="space-y-1">
                              <Label
                                htmlFor={`email-${account.id}`}
                                className="text-[11px] text-muted-foreground"
                              >
                                Email
                              </Label>
                              <Input
                                id={`email-${account.id}`}
                                value={editEmail}
                                onChange={(e) => setEditEmail(e.target.value)}
                                className="h-8 font-mono text-xs"
                              />
                            </div>
                            <div className="space-y-1">
                              <Label
                                htmlFor={`pw-${account.id}`}
                                className="text-[11px] text-muted-foreground"
                              >
                                New password (optional)
                              </Label>
                              <Input
                                id={`pw-${account.id}`}
                                type="password"
                                value={editPassword}
                                onChange={(e) =>
                                  setEditPassword(e.target.value)
                                }
                                placeholder="Leave blank to keep"
                                className="h-8 text-xs"
                              />
                            </div>
                          </div>
                        ) : (
                          <>
                            <div className="font-medium">{account.email}</div>
                            <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                              {roleLabel(String(account.role))}
                              {isSelf ? " · you" : ""}
                            </div>
                          </>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {editing ? (
                          <div className="space-y-1 max-w-[7rem]">
                            <Label
                              htmlFor={`slots-${account.id}`}
                              className="text-[11px] text-muted-foreground"
                            >
                              Slot limit
                            </Label>
                            <Input
                              id={`slots-${account.id}`}
                              value={editSlots}
                              onChange={(e) => setEditSlots(e.target.value)}
                              placeholder={
                                account.role === "admin" ? "unlimited" : "5"
                              }
                              className="h-8 font-mono text-xs"
                            />
                          </div>
                        ) : (
                          <span className="font-mono text-xs text-muted-foreground">
                            {account.config_slot_limit == null
                              ? `${account.config_slots_used ?? 0} / ∞`
                              : `${account.config_slots_used ?? 0} / ${account.config_slot_limit}`}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs text-muted-foreground">
                          {formatWhen(account.last_login_at)}
                        </div>
                        <div className="mt-0.5 font-mono text-[11px] text-muted-foreground/80">
                          <PrivateWanIp ip={account.last_login_ip} />
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            "inline-flex items-center rounded-md border px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide",
                            account.locked
                              ? "border-destructive/40 bg-destructive/10 text-destructive"
                              : "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                          )}
                        >
                          {account.locked ? "Locked" : "Active"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap justify-end gap-2">
                          {editing ? (
                            <>
                              <Button
                                type="button"
                                size="sm"
                                className="brand-btn-gradient"
                                disabled={busy}
                                onClick={() => void saveEdit(account)}
                              >
                                Save
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={cancelEdit}
                              >
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() => startEdit(account)}
                              >
                                Edit
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                disabled={busy || isSelf}
                                title={
                                  isSelf
                                    ? "You cannot lock your own account"
                                    : account.locked
                                      ? "Unlock account"
                                      : "Lock account"
                                }
                                onClick={() => void toggleLock(account)}
                              >
                                {account.locked ? (
                                  <LockOpen className="size-3.5" />
                                ) : (
                                  <Lock className="size-3.5" />
                                )}
                                {account.locked ? "Unlock" : "Lock"}
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="destructive"
                                disabled={busy || isSelf}
                                title={
                                  isSelf
                                    ? "You cannot delete your own account"
                                    : "Delete account"
                                }
                                onClick={() => void onDelete(account)}
                              >
                                <Trash2 className="size-3.5" />
                                Delete
                              </Button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
