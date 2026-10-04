"use client";

// Hand-rolled SVG/HTML charts. Rules followed throughout: status colors carry
// outcome state and always sit beside a text label; agent identity uses the
// fixed categorical slots; text never wears a data color; every mark has a
// hover tooltip and the numbers are also available as text.

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { AgentSummary } from "@/lib/api";
import { ms, pct } from "@/lib/format";
import { outcomeMeta, sortOutcomes } from "@/lib/outcomes";

const TONE_VAR: Record<string, string> = {
  good: "var(--st-good)",
  warning: "var(--st-warning)",
  serious: "var(--st-serious)",
  critical: "var(--st-critical)",
  neutral: "var(--st-neutral)",
};

export const outcomeColor = (cls: string) => TONE_VAR[outcomeMeta(cls).tone];

type Tip = { x: number; y: number; content: ReactNode } | null;

function useTip() {
  const ref = useRef<HTMLDivElement>(null);
  const [tip, setTip] = useState<Tip>(null);
  const show = (e: React.MouseEvent | React.FocusEvent, content: ReactNode) => {
    const box = ref.current?.getBoundingClientRect();
    const target = (e.currentTarget as Element).getBoundingClientRect();
    if (!box) return;
    const x = "clientX" in e && e.clientX ? e.clientX - box.left : target.left + target.width / 2 - box.left;
    setTip({ x, y: target.top - box.top, content });
  };
  const node = tip ? (
    <div className="chart-tip" style={{ left: tip.x, top: tip.y }} role="tooltip">
      {tip.content}
    </div>
  ) : null;
  return { ref, show, hide: () => setTip(null), node };
}

/** Horizontal 100% bar of outcome classes, with a labeled legend underneath. */
export function OutcomeBar({ counts, total, legend = true }: { counts: Record<string, number>; total: number; legend?: boolean }) {
  const { ref, show, hide, node } = useTip();
  const entries = sortOutcomes(Object.entries(counts)).filter(([, n]) => n > 0);
  if (!total) return <div className="stackbar" style={{ background: "var(--surface-2)" }} />;
  return (
    <div className="chart stack-sm" ref={ref}>
      <div className="stackbar" role="img" aria-label={entries.map(([c, n]) => `${outcomeMeta(c).label} ${n}`).join(", ")}>
        {entries.map(([cls, n]) => (
          <span
            key={cls}
            tabIndex={0}
            style={{ flexGrow: n, flexBasis: 0, background: outcomeColor(cls) }}
            onMouseMove={(e) =>
              show(
                e,
                <>
                  <strong>{outcomeMeta(cls).label}</strong> · {n} ({pct(n / total)})
                </>,
              )
            }
            onFocus={(e) => show(e, `${outcomeMeta(cls).label} · ${n}`)}
            onMouseLeave={hide}
            onBlur={hide}
          />
        ))}
      </div>
      {legend && (
        <div className="legend">
          {entries.map(([cls, n]) => (
            <span key={cls} className="legend-item" title={outcomeMeta(cls).hint}>
              <span className="swatch" style={{ background: outcomeColor(cls) }} />
              {outcomeMeta(cls).label} <span className="num faint">{n}</span>
            </span>
          ))}
        </div>
      )}
      {node}
    </div>
  );
}

function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0];
  const raw = max / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const ticks = [];
  for (let v = 0; v < max + step - 1e-9; v += step) ticks.push(Number(v.toFixed(6)));
  return ticks;
}

/** Latency distribution: equal-width bins up to p99, with p50/p95 markers. */
export function LatencyHistogram({
  histogram,
  p50,
  p95,
  color = "var(--series-1)",
  height = 140,
}: {
  histogram: { edges: number[]; counts: number[]; overflow: number };
  p50?: number | null;
  p95?: number | null;
  color?: string;
  height?: number;
}) {
  const { ref, show, hide, node } = useTip();
  const [width, setWidth] = useState(520);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  const { edges, counts, overflow } = histogram;
  const maxCount = Math.max(...counts, 1);
  const pad = { l: 32, r: 8, t: 34, b: 22 };
  const w = Math.max(200, width) - pad.l - pad.r;
  const h = height - pad.t - pad.b;
  const lo = edges[0];
  const hi = edges[edges.length - 1];
  const x = (v: number) => pad.l + ((v - lo) / (hi - lo || 1)) * w;
  const slot = w / counts.length;
  const barW = Math.min(24, Math.max(2, slot - 2));
  const yTicks = niceTicks(maxCount, 3).filter((t) => Number.isInteger(t));
  const yMax = Math.max(maxCount, yTicks[yTicks.length - 1] ?? maxCount);
  const y = (v: number) => pad.t + h - (v / yMax) * h;
  const xTicks = niceTicks(hi, 4).filter((t) => t >= lo && t <= hi);

  const marker = (v: number | null | undefined, label: string, row: number) => {
    if (v == null || v < lo || v > hi) return null;
    const nearRight = x(v) > pad.l + w * 0.75;
    return (
      <g>
        <line x1={x(v)} x2={x(v)} y1={pad.t - 6 - row * 12} y2={pad.t + h} stroke="var(--text-2)" strokeWidth={1} />
        <text x={x(v) + (nearRight ? -4 : 4)} y={pad.t - 8 - row * 12} textAnchor={nearRight ? "end" : "start"} fontSize={11} fill="var(--text-2)">
          {label} {ms(v)}
        </text>
      </g>
    );
  };

  return (
    <div className="chart" ref={ref}>
      <svg width="100%" height={height} viewBox={`0 0 ${Math.max(200, width)} ${height}`} role="img" aria-label="Latency distribution">
        <g className="grid">
          {yTicks.map((t) => (
            <line key={t} x1={pad.l} x2={pad.l + w} y1={y(t)} y2={y(t)} />
          ))}
        </g>
        <g className="axis">
          {yTicks.map((t) => (
            <text key={t} x={pad.l - 6} y={y(t) + 4} textAnchor="end">
              {t}
            </text>
          ))}
          {xTicks.map((t) => (
            <text key={t} x={x(t)} y={height - 4} textAnchor="middle">
              {ms(t)}
            </text>
          ))}
        </g>
        {counts.map((c, i) => {
          if (!c) return null;
          const bx = pad.l + i * slot + (slot - barW) / 2;
          const by = y(c);
          const bh = pad.t + h - by;
          const r = Math.min(4, barW / 2, bh);
          return (
            <path
              key={i}
              d={`M${bx},${pad.t + h} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + barW - r} Q${bx + barW},${by} ${bx + barW},${by + r} V${pad.t + h} Z`}
              fill={color}
              tabIndex={0}
              onMouseMove={(e) => show(e, <>{ms(edges[i])}–{ms(edges[i + 1])} · <strong>{c}</strong> result{c === 1 ? "" : "s"}</>)}
              onFocus={(e) => show(e, `${ms(edges[i])}–${ms(edges[i + 1])}: ${c}`)}
              onMouseLeave={hide}
              onBlur={hide}
            />
          );
        })}
        {/* Invisible full-height hit targets make thin bars easy to hover. */}
        {counts.map((c, i) => (
          <rect
            key={`hit-${i}`}
            x={pad.l + i * slot}
            y={pad.t}
            width={slot}
            height={h}
            fill="transparent"
            onMouseMove={(e) => show(e, <>{ms(edges[i])}–{ms(edges[i + 1])} · <strong>{c}</strong> result{c === 1 ? "" : "s"}</>)}
            onMouseLeave={hide}
          />
        ))}
        {marker(p50, "p50", 0)}
        {marker(p95, "p95", p50 != null && p95 != null && x(p95) - x(p50) < 90 ? 1 : 0)}
        <line x1={pad.l} x2={pad.l + w} y1={pad.t + h} y2={pad.t + h} stroke="var(--border-strong)" />
      </svg>
      {overflow > 0 && <div className="faint small">{overflow} slower result{overflow === 1 ? "" : "s"} beyond p99 not shown.</div>}
      {node}
    </div>
  );
}

/**
 * Agent comparison: one row per agent with a bar for the rate and a whisker
 * for its 95% confidence interval. Rows are direct-labeled with the agent name.
 */
export function RateComparison({
  rows,
}: {
  rows: { name: string; color: string; value: number | null; ci?: [number, number] | null; detail?: string }[];
}) {
  const { ref, show, hide, node } = useTip();
  return (
    <div className="chart stack-sm" ref={ref} role="list">
      {rows.map((r) => (
        <div key={r.name} role="listitem" className="row" style={{ flexWrap: "nowrap", gap: 12 }}>
          <span className="row truncate" style={{ width: 180, flex: "none", gap: 6 }} title={r.name}>
            <span className="swatch" style={{ background: r.color }} />
            <span className="truncate">{r.name}</span>
          </span>
          <div
            className="grow"
            style={{ position: "relative", height: 18 }}
            onMouseMove={(e) =>
              show(
                e,
                <>
                  <strong>{pct(r.value)}</strong>
                  {r.ci ? ` · 95% CI ${pct(r.ci[0])}–${pct(r.ci[1])}` : ""}
                  {r.detail ? ` · ${r.detail}` : ""}
                </>,
              )
            }
            onMouseLeave={hide}
          >
            <div style={{ position: "absolute", inset: "4px 0", background: "var(--surface-2)", borderRadius: 4 }} />
            {r.value != null && (
              <div
                style={{
                  position: "absolute",
                  left: 0,
                  top: 4,
                  bottom: 4,
                  width: `${r.value * 100}%`,
                  background: r.color,
                  borderRadius: "0 4px 4px 0",
                  minWidth: 2,
                }}
              />
            )}
            {r.ci && (
              <div
                aria-hidden
                style={{
                  position: "absolute",
                  top: 1,
                  bottom: 1,
                  left: `${r.ci[0] * 100}%`,
                  width: `${Math.max(0.5, (r.ci[1] - r.ci[0]) * 100)}%`,
                  borderLeft: "1.5px solid var(--text)",
                  borderRight: "1.5px solid var(--text)",
                  backgroundImage: "linear-gradient(var(--text), var(--text))",
                  backgroundSize: "100% 1.5px",
                  backgroundPosition: "center",
                  backgroundRepeat: "no-repeat",
                }}
              />
            )}
          </div>
          <span className="num" style={{ width: 56, textAlign: "right", fontWeight: 600 }}>
            {pct(r.value)}
          </span>
        </div>
      ))}
      {node}
    </div>
  );
}

/** Small latency range strip per agent: min–p99 track, dots for p50/p95. */
export function LatencyComparison({ agents, colors }: { agents: AgentSummary[]; colors: string[] }) {
  const { ref, show, hide, node } = useTip();
  const max = useMemo(() => Math.max(1, ...agents.map((a) => a.scalars.latency_ms?.p99 ?? 0)), [agents]);
  const ticks = niceTicks(max, 3);
  const top = ticks[ticks.length - 1] || max;
  const pos = (v: number | null | undefined) => `${((v ?? 0) / top) * 100}%`;
  return (
    <div className="chart stack-sm" ref={ref}>
      {agents.map((a, i) => {
        const l = a.scalars.latency_ms;
        return (
          <div key={a.agent_id} className="row" style={{ flexWrap: "nowrap", gap: 12 }}>
            <span className="row truncate" style={{ width: 180, flex: "none", gap: 6 }} title={a.agent_name}>
              <span className="swatch" style={{ background: colors[i] }} />
              <span className="truncate">{a.agent_name}</span>
            </span>
            <div
              className="grow"
              style={{ position: "relative", height: 20 }}
              onMouseMove={(e) => show(e, <>p50 <strong>{ms(l?.p50)}</strong> · p95 <strong>{ms(l?.p95)}</strong> · p99 {ms(l?.p99)} · min {ms(l?.min)}</>)}
              onMouseLeave={hide}
            >
              <div style={{ position: "absolute", left: 0, right: 0, top: 9, height: 1, background: "var(--grid)" }} />
              <div style={{ position: "absolute", left: pos(l?.min), width: `calc(${pos(l?.p99)} - ${pos(l?.min)})`, top: 8, height: 4, borderRadius: 4, background: colors[i], opacity: 0.35 }} />
              {(["p50", "p95"] as const).map((k) => (
                <span
                  key={k}
                  style={{
                    position: "absolute",
                    left: pos(l?.[k]),
                    top: 5,
                    width: 10,
                    height: 10,
                    marginLeft: -5,
                    borderRadius: "50%",
                    background: k === "p50" ? colors[i] : "var(--surface)",
                    border: `2px solid ${colors[i]}`,
                    boxShadow: "0 0 0 2px var(--surface)",
                  }}
                />
              ))}
            </div>
            <span className="num small" style={{ width: 110, textAlign: "right" }}>
              {ms(l?.p50)} <span className="faint">/ {ms(l?.p95)}</span>
            </span>
          </div>
        );
      })}
      <div className="row" style={{ flexWrap: "nowrap", gap: 12 }} aria-hidden>
        <span style={{ width: 180, flex: "none" }} />
        <div className="grow faint small num" style={{ position: "relative", height: 16 }}>
          {ticks.map((t, i) => (
            <span
              key={t}
              style={{
                position: "absolute",
                left: pos(t),
                transform: i === 0 ? "none" : "translateX(-50%)",
                whiteSpace: "nowrap",
              }}
            >
              {ms(t)}
            </span>
          ))}
        </div>
        <span style={{ width: 110, flex: "none" }} />
      </div>
      <div className="legend">
        <span className="legend-item">
          <span className="swatch" style={{ borderRadius: "50%", background: "var(--text-2)" }} /> p50 (median)
        </span>
        <span className="legend-item">
          <span className="swatch" style={{ borderRadius: "50%", border: "2px solid var(--text-2)" }} /> p95
        </span>
        <span className="legend-item">
          <span className="swatch" style={{ height: 4, background: "var(--text-3)" }} /> min–p99 range
        </span>
      </div>
      {node}
    </div>
  );
}
