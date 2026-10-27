import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "DeepTune — Neuro-Symbolic Query Optimizer",
  description:
    "Local-first PostgreSQL query plan explorer and index recommender. GNN cost prediction with symbolic pruning and beam search.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#09090b",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable} dark`}
      suppressHydrationWarning
    >
      <body className="bg-surface-0 text-content-primary antialiased">
        {children}
        <Toaster
          theme="dark"
          position="bottom-right"
          closeButton
          className="font-sans"
        />
      </body>
    </html>
  );
}
