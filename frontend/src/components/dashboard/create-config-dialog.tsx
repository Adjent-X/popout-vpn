"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ApiError,
  createConfig,
  downloadOvpnText,
  downloadWgText,
  type CreateConfigResponse,
} from "@/lib/api";

type ExpiryMode = "7" | "30" | "90" | "365" | "custom";

type CreateConfigDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (config: CreateConfigResponse) => void;
};

export function CreateConfigDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateConfigDialogProps) {
  const [label, setLabel] = useState("");
  const [expiryMode, setExpiryMode] = useState<ExpiryMode>("30");
  const [customDate, setCustomDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<CreateConfigResponse | null>(null);

  function reset() {
    setLabel("");
    setExpiryMode("30");
    setCustomDate("");
    setError(null);
    setSubmitting(false);
    setCreated(null);
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset();
    onOpenChange(next);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!label.trim()) {
      setError("Please enter a name for this VPN access.");
      return;
    }
    if (expiryMode === "custom" && !customDate) {
      setError("Please pick an end date.");
      return;
    }

    setSubmitting(true);
    try {
      const body =
        expiryMode === "custom"
          ? {
              label: label.trim(),
              expires_at: new Date(`${customDate}T23:59:59`).toISOString(),
            }
          : {
              label: label.trim(),
              expiry_days: Number(expiryMode) as 7 | 30 | 90 | 365,
            };

      const result = await createConfig(body);
      setCreated(result);
      onCreated(result);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not create the VPN file. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md" showCloseButton>
        {created ? (
          <>
            <DialogHeader>
              <DialogTitle>VPN file ready</DialogTitle>
              <DialogDescription>
                Access for <strong>{created.label}</strong> was created. Choose
                OpenVPN (<span className="font-mono">.ovpn</span>) or WireGuard
                (<span className="font-mono">.conf</span>), then send the file
                to the person who needs VPN access.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter className="flex-col gap-2 sm:flex-col sm:space-x-0">
              <Button
                type="button"
                className="brand-btn-gradient w-full"
                onClick={() =>
                  downloadOvpnText(`${created.client_name}.ovpn`, created.ovpn)
                }
              >
                Download .ovpn (OpenVPN)
              </Button>
              {created.wg_conf ? (
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={() =>
                    downloadWgText(`${created.client_name}.conf`, created.wg_conf!)
                  }
                >
                  Download .conf (WireGuard)
                </Button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                className="w-full"
                onClick={() => handleOpenChange(false)}
              >
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form onSubmit={onSubmit} className="space-y-4">
            <DialogHeader>
              <DialogTitle>Create VPN access</DialogTitle>
              <DialogDescription>
                Give this access a clear name (for example a person or company),
                then choose how long it should last.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <Label htmlFor="config-label">Name</Label>
              <Input
                id="config-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Acme Corp — Jane"
                className="h-10"
                autoFocus
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="expiry-mode">How long should it last?</Label>
              <select
                id="expiry-mode"
                value={expiryMode}
                onChange={(e) => setExpiryMode(e.target.value as ExpiryMode)}
                className="flex h-10 w-full rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
              >
                <option value="7">7 days</option>
                <option value="30">30 days</option>
                <option value="90">90 days</option>
                <option value="365">1 year</option>
                <option value="custom">Pick a custom end date</option>
              </select>
            </div>

            {expiryMode === "custom" && (
              <div className="space-y-2">
                <Label htmlFor="custom-date">End date</Label>
                <Input
                  id="custom-date"
                  type="date"
                  value={customDate}
                  min={new Date().toISOString().slice(0, 10)}
                  onChange={(e) => setCustomDate(e.target.value)}
                  className="h-10"
                />
              </div>
            )}

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
                onClick={() => handleOpenChange(false)}
                disabled={submitting}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={submitting}
                className="brand-btn-gradient"
              >
                {submitting ? "Creating…" : "Create"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
