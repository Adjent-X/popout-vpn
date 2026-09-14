"use client";

import { Turnstile, type TurnstileInstance } from "@marsidev/react-turnstile";
import { useRef } from "react";

import { usePublicConfig } from "@/components/brand-provider";

type TurnstileFieldProps = {
  onToken: (token: string) => void;
  onExpire?: () => void;
  onError?: () => void;
};

export function TurnstileField({
  onToken,
  onExpire,
  onError,
}: TurnstileFieldProps) {
  const ref = useRef<TurnstileInstance | null>(null);
  const { turnstile_enabled, turnstile_site_key } = usePublicConfig();

  if (!turnstile_enabled) {
    return null;
  }

  if (!turnstile_site_key) {
    return (
      <p className="font-mono text-xs text-destructive">
        Turnstile is enabled but no site key is configured
      </p>
    );
  }

  return (
    <div className="flex min-h-[65px] items-center">
      <Turnstile
        ref={ref}
        siteKey={turnstile_site_key}
        options={{
          theme: "dark",
          size: "flexible",
          retry: "auto",
          refreshExpired: "auto",
        }}
        onSuccess={onToken}
        onExpire={() => {
          onExpire?.();
          ref.current?.reset();
        }}
        onError={() => {
          onError?.();
        }}
      />
    </div>
  );
}
