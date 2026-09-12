import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Port 25", description: "Autonomous email negotiation console" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
