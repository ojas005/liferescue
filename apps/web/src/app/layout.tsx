import type { Metadata } from "next";
import { MockBanner } from "@/components/MockBanner";
import { NavBar } from "@/components/NavBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "LifeRescue",
  description: "One platform for LifeRescue, ScamShield and LifeOS.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <MockBanner />
        <NavBar />
        <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
        <footer className="mx-auto max-w-6xl px-4 pb-10 text-xs text-slate-500">
          Hackathon build. Actions that affect the outside world require your approval.
        </footer>
      </body>
    </html>
  );
}
