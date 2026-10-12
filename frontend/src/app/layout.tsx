import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: process.env.NEXT_PUBLIC_APP_TITLE ?? "AIL Demand Forecast",
  description: "AIL Demand Forecast — 12-month statistical demand forecast from AIL steel sales.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <Nav />
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
