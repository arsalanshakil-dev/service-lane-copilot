import type { Metadata } from "next";
import Script from "next/script";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Service Lane Copilot",
  description: "Synthetic-data demo for dealership service advisors.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        {children}
        <Script id="theme-preference" strategy="beforeInteractive">{`try { const theme = localStorage.getItem("service-lane-theme"); if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme; } catch {}`}</Script>
      </body>
    </html>
  );
}
