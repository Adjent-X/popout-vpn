"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ClientConfig } from "@/lib/api";

export type ConfigActionMode = "revoke" | "delete" | "reissue";

type ConfigActionDialogProps = {
  config: ClientConfig | null;
  mode: ConfigActionMode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  busy: boolean;
  error: string | null;
};

export function ConfigActionDialog({
  config,
  mode,
  open,
  onOpenChange,
  onConfirm,
  busy,
  error,
}: ConfigActionDialogProps) {
  const label = config?.label ?? "this person";

  const title =
    mode === "revoke"
      ? "Revoke this VPN access?"
      : mode === "delete"
        ? "Delete this revoked config?"
        : "Reissue VPN access?";

  const cancel =
    mode === "revoke" ? "Keep access" : mode === "delete" ? "Keep row" : "Cancel";

  const confirm =
    mode === "revoke"
      ? "Yes, revoke access"
      : mode === "delete"
        ? "Yes, delete"
        : "Reissue & download";

  const confirming =
    mode === "revoke"
      ? "Revoking…"
      : mode === "delete"
        ? "Deleting…"
        : "Reissuing…";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {mode === "revoke" && (
              <>
                This permanently turns off VPN access for{" "}
                <strong>{label}</strong>. They will not be able to connect again
                with this file. You can reissue a new file later or delete the
                row.
              </>
            )}
            {mode === "delete" && (
              <>
                Remove <strong>{label}</strong> from the list. The certificate
                stays revoked on the VPN server; this only cleans up the record.
              </>
            )}
            {mode === "reissue" && (
              <>
                A revoked certificate cannot be turned back on. This creates a
                new certificate for <strong>{label}</strong> and a fresh .ovpn
                file to download. The old file stays unusable.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-xs text-destructive"
          >
            {error}
          </p>
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={busy}
          >
            {cancel}
          </Button>
          <Button
            type="button"
            variant={mode === "reissue" ? "default" : "destructive"}
            className={mode === "reissue" ? "brand-btn-gradient" : undefined}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? confirming : confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
