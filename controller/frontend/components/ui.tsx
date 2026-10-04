"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import type { RunStatus } from "@/lib/api";
import { outcomeMeta } from "@/lib/outcomes";
import { IconAlert, IconCheck, IconCopy, IconInfo } from "./icons";

export function PageHeader({
  title,
  subtitle,
  crumbs,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  crumbs?: { href: string; label: string }[];
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div className="grow">
        {crumbs && (
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c) => (
              <span key={c.href} className="row" style={{ gap: 6 }}>
                <Link href={c.href}>{c.label}</Link>
                <span aria-hidden>/</span>
              </span>
            ))}
          </nav>
        )}
        <h1>{title}</h1>
        {subtitle && <p className="subtitle">{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Card({
  title,
  hint,
  actions,
  children,
  flush,
  id,
}: {
  title?: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  id?: string;
}) {
  return (
    <section className="card" id={id}>
      {(title || actions) && (
        <div className="card-header">
          <div>
            {title && <h2>{title}</h2>}
            {hint && <p className="hint">{hint}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      <div className={`card-body${flush ? " flush" : ""}`}>{children}</div>
    </section>
  );
}

export function Field({
  label,
  hint,
  error,
  optional,
  children,
  htmlFor,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  optional?: boolean;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={htmlFor}>
        {label}
        {optional && <span className="optional">optional</span>}
      </label>
      {children}
      {error ? <span className="field-error">{error}</span> : hint ? <span className="field-hint">{hint}</span> : null}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="row" role="status" style={{ gap: 8 }}>
      <span className="spinner" />
      {label && <span className="muted">{label}</span>}
    </span>
  );
}

export function Skeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="stack-sm" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  children,
  actions,
}: {
  icon?: ReactNode;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="empty">
      {icon && <div className="empty-icon">{icon}</div>}
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {actions && <div className="row" style={{ justifyContent: "center", marginTop: 6 }}>{actions}</div>}
    </div>
  );
}

export function Callout({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "danger" | "warning" | "neutral";
  title?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="callout" data-tone={tone} role={tone === "danger" ? "alert" : undefined}>
      {tone === "info" || tone === "neutral" ? <IconInfo /> : <IconAlert />}
      <div className="grow">
        {title && <div style={{ fontWeight: 600 }}>{title}</div>}
        {children && <div className={title ? "muted" : undefined}>{children}</div>}
      </div>
    </div>
  );
}

/** Renders any thrown error; ApiErrors list their field problems. */
export function ErrorCallout({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null;
  if (error instanceof ApiError) {
    return (
      <Callout tone="danger" title={title ?? error.detail}>
        {title && <p>{error.detail}</p>}
        {error.errors.length > 0 && (
          <ul>
            {error.errors.slice(0, 12).map((e, i) => (
              <li key={i}>
                {e.line ? <strong>Line {e.line}: </strong> : e.loc ? <code>{e.loc}</code> : null} {e.message}
              </li>
            ))}
            {error.errors.length > 12 && <li>…and {error.errors.length - 12} more</li>}
          </ul>
        )}
      </Callout>
    );
  }
  return <Callout tone="danger" title={title ?? "Something went wrong"}>{String(error)}</Callout>;
}

const RUN_TONE: Record<RunStatus, { tone: string; label: string; live?: boolean }> = {
  queued: { tone: "neutral", label: "Queued", live: true },
  running: { tone: "info", label: "Running", live: true },
  completed: { tone: "good", label: "Completed" },
  failed: { tone: "critical", label: "Failed" },
  cancelled: { tone: "neutral", label: "Cancelled" },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const s = RUN_TONE[status] ?? { tone: "neutral", label: status };
  return (
    <span className="badge" data-tone={s.tone} data-live={s.live ? "true" : undefined}>
      <span className="dot" />
      {s.label}
    </span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: string }) {
  const m = outcomeMeta(outcome);
  return (
    <span className="badge" data-tone={m.tone} title={m.hint}>
      <span className="dot" />
      {m.label}
    </span>
  );
}

export function ProgressBar({ value, total }: { value: number; total: number }) {
  const indeterminate = total <= 0;
  const pctValue = indeterminate ? 0 : Math.min(100, (value / total) * 100);
  return (
    <div
      className="progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={total || undefined}
      aria-valuenow={indeterminate ? undefined : value}
      data-indeterminate={indeterminate ? "true" : undefined}
    >
      <span style={{ width: `${pctValue}%` }} />
    </div>
  );
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-sm btn-icon copy"
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard unavailable (insecure context) */
        }
      }}
    >
      {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
    </button>
  );
}

export function CodeBlock({ value, maxHeight, wrap = true }: { value: unknown; maxHeight?: number; wrap?: boolean }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="code-block">
      <pre className={`code${wrap ? "" : " nowrap-code"}`} style={maxHeight ? { maxHeight } : undefined}>
        {text || <span className="faint">(empty)</span>}
      </pre>
      {text && <CopyButton text={text} />}
    </div>
  );
}

export function Stat({ label, value, sub, title }: { label: ReactNode; value: ReactNode; sub?: ReactNode; title?: string }) {
  return (
    <div className="stat" title={title}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
}: {
  value: T;
  onChange: (v: T) => void;
  tabs: { value: T; label: ReactNode }[];
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.value}
          type="button"
          role="tab"
          className="tab"
          aria-selected={value === t.value}
          onClick={() => onChange(t.value)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
