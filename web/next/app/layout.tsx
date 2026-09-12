import type { Metadata } from "next";
import { CopilotKitProvider } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import "./globals.css";

export const metadata: Metadata = { title: "Port 25", description: "Autonomous email negotiation console" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><CopilotKitProvider runtimeUrl="/api/copilotkit">{children}</CopilotKitProvider></body></html>;
}
