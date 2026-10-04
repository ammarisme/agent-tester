"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Meta } from "@/lib/api";
import { FeedbackProvider } from "./overlays";
import {
  IconAgent,
  IconBolt,
  IconBook,
  IconDataset,
  IconHome,
  IconMenu,
  IconMoon,
  IconRun,
  IconSun,
} from "./icons";

const NAV = [
  { href: "/", label: "Overview", icon: IconHome, exact: true },
  { href: "/agents", label: "Agents", icon: IconAgent },
  { href: "/datasets", label: "Datasets", icon: IconDataset },
  { href: "/runs", label: "Runs", icon: IconRun },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);
  useEffect(() => {
    const stored = document.documentElement.dataset.theme as "light" | "dark" | undefined;
    setTheme(stored ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  }, []);
  if (!theme) return null;
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="btn btn-ghost btn-sm"
      onClick={() => {
        document.documentElement.dataset.theme = next;
        try {
          localStorage.setItem("theme", next);
        } catch {
          /* storage unavailable */
        }
        setTheme(next);
      }}
      aria-label={`Switch to ${next} theme`}
    >
      {theme === "dark" ? <IconSun size={14} /> : <IconMoon size={14} />}
      {theme === "dark" ? "Light" : "Dark"} theme
    </button>
  );
}

function ServerStatus() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    let alive = true;
    const check = () =>
      api
        .meta()
        .then((m) => alive && (setMeta(m), setDown(false)))
        .catch(() => alive && setDown(true));
    check();
    const t = setInterval(check, 30_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  if (down)
    return (
      <span className="badge" data-tone="critical">
        <span className="dot" />
        API unreachable
      </span>
    );
  if (!meta) return null;
  return (
    <div className="stack-sm" style={{ gap: 4 }}>
      <span className="row" style={{ gap: 6 }} title="Controller API is reachable">
        <span className="dot" style={{ background: "var(--st-good)" }} /> v{meta.version} ·{" "}
        {meta.runner_mode === "inprocess" ? "in-process runner" : "Docker runner"}
      </span>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  const isActive = (href: string, exact?: boolean) =>
    exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);

  return (
    <FeedbackProvider>
      <div className="shell">
        <aside className="sidebar" data-open={open ? "true" : undefined} aria-label="Main navigation">
          <Link href="/" className="brand">
            <span className="brand-mark">
              <IconBolt size={15} />
            </span>
            Agent Tester
          </Link>
          <nav className="stack-sm" style={{ gap: 2 }}>
            {NAV.map(({ href, label, icon: Icon, exact }) => (
              <Link
                key={href}
                href={href}
                className="nav-link"
                aria-current={isActive(href, exact) ? "page" : undefined}
              >
                <Icon />
                {label}
              </Link>
            ))}
          </nav>
          <div className="sidebar-footer">
            <a className="nav-link" style={{ padding: "4px 0" }} href="/api/docs" target="_blank" rel="noreferrer">
              <IconBook size={14} /> API reference
            </a>
            <ThemeToggle />
            <ServerStatus />
          </div>
        </aside>
        {open && <div className="overlay" style={{ zIndex: 35 }} onClick={() => setOpen(false)} />}
        <div>
          <div className="mobile-bar">
            <button type="button" className="btn btn-icon" onClick={() => setOpen(true)} aria-label="Open navigation">
              <IconMenu />
            </button>
            <strong>Agent Tester</strong>
          </div>
          <main className="content" id="main">
            {children}
          </main>
        </div>
      </div>
    </FeedbackProvider>
  );
}
