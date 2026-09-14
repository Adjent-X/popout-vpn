"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useTheme } from "@/components/theme-provider";

/** Redirects sub-admins away from full-admin-only pages. */
export function AdminOnlyGate({ children }: { children: React.ReactNode }) {
  const { admin } = useTheme();
  const router = useRouter();
  const isSubAdmin = admin?.role === "sub_admin";

  useEffect(() => {
    if (isSubAdmin) {
      router.replace("/dashboard");
    }
  }, [isSubAdmin, router]);

  if (!admin || isSubAdmin) {
    return (
      <div className="font-mono text-sm text-muted-foreground">Loading…</div>
    );
  }

  return <>{children}</>;
}
