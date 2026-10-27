import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FinSight | Financial analytics",
  description: "A transparent financial statement analysis workspace. Under development.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
