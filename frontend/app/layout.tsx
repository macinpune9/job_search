import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "JobPilot", description: "Job discovery, ATS resume tailoring and application tracking" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
