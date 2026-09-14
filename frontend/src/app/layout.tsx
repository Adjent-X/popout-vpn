import type { Metadata } from "next";
import { JetBrains_Mono, Space_Grotesk } from "next/font/google";
import { cookies } from "next/headers";

import { BrandProvider } from "@/components/brand-provider";
import { DocumentTitle } from "@/components/document-title";
import { PublicGateProvider } from "@/components/public-gate-provider";
import {
  BRAND_FOUC_SCRIPT,
  brandCssVars,
  getInitialPublicShell,
} from "@/lib/initial-public-shell";

import "./globals.css";

export const dynamic = "force-dynamic";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-sans",
  subsets: ["latin"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

async function loadShell() {
  const jar = await cookies();
  const cookieHeader = jar
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  return getInitialPublicShell(cookieHeader || null);
}

export async function generateMetadata(): Promise<Metadata> {
  const shell = await loadShell();
  return {
    title: shell.site_title || "Popout VPN Admin",
    description: "Internal admin dashboard for OpenVPN client configs",
    icons: {
      icon: [{ url: "/favicon.svg", type: "image/svg+xml" }],
      shortcut: ["/favicon.svg"],
    },
  };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const shell = await loadShell();

  return (
    <html
      lang="en"
      className={`dark ${spaceGrotesk.variable} ${jetbrainsMono.variable} h-full antialiased`}
      style={brandCssVars(shell.colors)}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: BRAND_FOUC_SCRIPT }} />
      </head>
      <body className="flex min-h-full flex-col overflow-x-hidden font-sans">
        <BrandProvider initialShell={shell}>
          <PublicGateProvider>
            <DocumentTitle />
            {children}
          </PublicGateProvider>
        </BrandProvider>
      </body>
    </html>
  );
}
