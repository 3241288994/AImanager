import type { Metadata } from "next";
import "./globals.css";
import { AppFrame } from "@/components/layout/app-frame";
import { Providers } from "@/components/providers";
import { AppBootstrap } from "@/components/layout/app-bootstrap";
import {
  appearanceInitScript,
  DEFAULT_APPEARANCE_PRESET,
} from "@/lib/appearance";

export const metadata: Metadata = {
  title: "AImanager",
  description: "Local-first AI CLI, private API, account and workspace management",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      suppressHydrationWarning
      data-appearance={DEFAULT_APPEARANCE_PRESET}
    >
      <body className="antialiased">
        <script dangerouslySetInnerHTML={{ __html: appearanceInitScript }} />
        <Providers>
          <AppBootstrap>
            <AppFrame>{children}</AppFrame>
          </AppBootstrap>
        </Providers>
      </body>
    </html>
  );
}
