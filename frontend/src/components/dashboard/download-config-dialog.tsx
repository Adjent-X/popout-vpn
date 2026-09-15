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
import {
  ApiError,
  downloadConfigFile,
  downloadOvpnText,
  downloadWgText,
} from "@/lib/api";

export type DownloadConfigTarget = {
  clientName: string;
  configId?: string;
  ovpn?: string;
  wgConf?: string | null;
  wireguardInstalled?: boolean;
};

type DownloadConfigDialogProps = {
  target: DownloadConfigTarget | null;
  onOpenChange: (open: boolean) => void;
};

export function DownloadConfigDialog({
  target,
  onOpenChange,
}: DownloadConfigDialogProps) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"ovpn" | "wg" | null>(null);

  const open = Boolean(target);
  const showWg =
    Boolean(target?.wgConf) ||
    Boolean(target?.configId && target?.wireguardInstalled !== false);

  async function downloadOvpn() {
    if (!target) return;
    setError(null);
    setBusy("ovpn");
    try {
      if (target.ovpn) {
        downloadOvpnText(`${target.clientName}.ovpn`, target.ovpn);
        return;
      }
      if (target.configId) {
        await downloadConfigFile(
          target.configId,
          `${target.clientName}.ovpn`,
          "ovpn",
        );
      }
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "OpenVPN download failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  async function downloadWg() {
    if (!target) return;
    setError(null);
    setBusy("wg");
    try {
      if (target.wgConf) {
        downloadWgText(`${target.clientName}.conf`, target.wgConf);
        return;
      }
      if (target.configId) {
        await downloadConfigFile(
          target.configId,
          `${target.clientName}.conf`,
          "wg",
        );
      }
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "WireGuard download failed.",
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md" showCloseButton>
        <DialogHeader>
          <DialogTitle>Download VPN file</DialogTitle>
          <DialogDescription>
            Choose OpenVPN (<span className="font-mono">.ovpn</span>) or
            WireGuard (<span className="font-mono">.conf</span>) for{" "}
            <strong>{target?.clientName}</strong>.
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
        <DialogFooter className="flex-col gap-2 sm:flex-col sm:space-x-0">
          <Button
            type="button"
            className="brand-btn-gradient w-full"
            disabled={busy !== null}
            onClick={() => void downloadOvpn()}
          >
            {busy === "ovpn" ? "Downloading…" : "Download .ovpn (OpenVPN)"}
          </Button>
          {showWg && (
            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled={busy !== null}
              onClick={() => void downloadWg()}
            >
              {busy === "wg" ? "Downloading…" : "Download .conf (WireGuard)"}
            </Button>
          )}
          <Button
            type="button"
            variant="ghost"
            className="w-full"
            onClick={() => onOpenChange(false)}
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
