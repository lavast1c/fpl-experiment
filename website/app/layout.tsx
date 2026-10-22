import type { Metadata } from "next";
import Link from "next/link";
import { Barlow, Barlow_Condensed } from "next/font/google";
import "./globals.css";

const body = Barlow({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-body" });
const display = Barlow_Condensed({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-display" });

export const metadata: Metadata = {
  title: "AI Fantasy League",
  description:
    "Nine Claude agents and three simple bots manage simulated Fantasy Premier League teams for the 2026/27 season. Does memory help them learn, or do they learn the wrong lessons from luck?",
};

const NAV = [
  { href: "/", label: "Table" },
  { href: "/teams", label: "Teams" },
  { href: "/memory", label: "Memory" },
  { href: "/about", label: "About" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${body.variable} ${display.variable}`}>
      <body>
        <header className="site-header">
          <div className="wrap header-row">
            <Link href="/" className="wordmark">AI Fantasy League</Link>
            <nav aria-label="Main">
              {NAV.map((item) => (
                <Link key={item.href} href={item.href}>{item.label}</Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="wrap">{children}</main>
        <footer className="site-footer wrap">
          <p>
            A high school research project. Teams are simulated and scored by the project&apos;s own code from
            public FPL data; nothing is entered in the real game. FPL data belongs to the Premier League.
            Code and full dataset on <a href="https://github.com/lavast1c/fpl-experiment">GitHub</a>.
          </p>
        </footer>
      </body>
    </html>
  );
}
