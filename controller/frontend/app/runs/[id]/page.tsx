"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage, type AgentSummary, type ResultDetail, type ResultRow, type Run } from "@/lib/api";
import { absTime, count, ms, pct, relTime } from "@/lib/format";
import { useDebounced, useNow, useResource } from "@/lib/hooks";
import { outcomeMeta, seriesVar, sortOutcomes } from "@/lib/outcomes";
import { LatencyComparison, LatencyHistogram, OutcomeBar, RateComparison } from "@/components/charts";
import { IconChevron, IconDownload, IconRefresh, IconSearch, IconStop, IconTrash } from "@/components/icons";
import { Drawer, Menu, useFeedback } from "@/components/overlays";
import { ResultView } from "@/components/ResultView";
import { headline, runTitle } from "@/components/runs";
import {
  Callout,
  Card,
  EmptyState,
  ErrorCallout,
  OutcomeBadge,
  PageHeader,
  ProgressBar,
  RunStatusBadge,
  Skeleton,
  Spinner,
  Stat,
} from "@/components/ui";

const PAGE = 100;
const isActive = (r?: Run) => r?.status === "queued" || r?.status === "running";

// ── Summary ─────────────────────────────────────────────────────────

function rateLabel(s: AgentSummary) {
  return s.pass_rate != null ? "Pass rate" : "Success rate";
}

function AgentCard({ s, color }: { s: AgentSummary; color: string }) {
  const lat = s.scalars.latency_ms;
  const ci = s.pass_rate_ci95;
  const extra = Object.entries(s.scalars).filter(([k, v]) => k !== "latency_ms" && k !== "n_polls" && v.count > 0);
  return (
    <Card
      title={
        <span className="row" style={{ gap: 8 }}>
          <span className="swatch" style={{ background: color }} />
          {s.agent_name}
        </span>
      }
      hint={`${count(s.n_cases, "case")} × ${count(s.trials, "trial")} = ${count(s.n_results, "result")}`}
    >
      <div className="stack">
        <div className="stats">
          <Stat
            label={rateLabel(s)}
            value={pct(headline(s))}
            sub={ci ? `95% CI ${pct(ci[0], 0)}–${pct(ci[1], 0)}` : s.pass_rate == null ? "no expectations scored" : undefined}
            title="The Wilson 95% interval: where the true rate plausibly lies given this sample size."
          />
          <Stat label="Error rate" value={pct(s.error_rate)} sub="agent, timeout, network, config" />
          <Stat label="Latency p50" value={ms(lat?.p50)} sub={`mean ${ms(lat?.mean)}`} />
          <Stat label="Latency p95" value={ms(lat?.p95)} sub={`p99 ${ms(lat?.p99)}`} />
        </div>
        <div className="stack-sm">
          <h3>Outcomes</h3>
          <OutcomeBar counts={s.outcome_counts} total={s.n_results} />
        </div>
        {s.latency_histogram && (
          <div className="stack-sm">
            <h3>Latency distribution</h3>
            <LatencyHistogram histogram={s.latency_histogram} p50={lat?.p50} p95={lat?.p95} color={color} />
          </div>
        )}
        {s.consistency && (
          <div className="stack-sm">
            <h3>Consistency across {s.trials} trials</h3>
            <div className="stats">
              <Stat label="Every trial passed" value={pct(s.consistency.pass_all_trials_rate)} sub="of cases (pass^k)" />
              <Stat label="Any trial passed" value={pct(s.consistency.pass_any_trial_rate)} sub="of cases (pass@k)" />
              <Stat label="Flaky cases" value={s.consistency.flaky_cases} sub="mixed results" />
            </div>
            {s.consistency.flaky_case_ids.length > 0 && (
              <p className="small muted">
                Flaky:{" "}
                {s.consistency.flaky_case_ids.slice(0, 12).map((id) => (
                  <span key={id} className="tag mono" style={{ marginRight: 4 }}>
                    {id}
                  </span>
                ))}
              </p>
            )}
          </div>
        )}
        {extra.length > 0 && (
          <div className="stack-sm">
            <h3>Extracted metrics</h3>
            <table className="table">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th className="right">mean</th>
                  <th className="right">p50</th>
                  <th className="right">p95</th>
                  <th className="right">max</th>
                </tr>
              </thead>
              <tbody>
                {extra.map(([k, v]) => (
                  <tr key={k}>
                    <td className="mono small">{k}</td>
                    {[v.mean, v.p50, v.p95, v.max].map((x, i) => (
                      <td key={i} className="right num">
                        {x == null ? "—" : Number.isInteger(x) ? x : x.toFixed(2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}

function Comparison({ summaries, colors }: { summaries: AgentSummary[]; colors: string[] }) {
  const scored = summaries.some((s) => s.pass_rate != null);
  return (
    <Card title="Agent comparison" hint="Same cases, same trials. Overlapping intervals mean the difference may be noise — add cases or trials.">
      <div className="grid-2">
        <div className="stack-sm">
          <h3>{scored ? "Pass rate" : "Success rate"} with 95% CI</h3>
          <RateComparison
            rows={summaries.map((s, i) => ({
              name: s.agent_name,
              color: colors[i],
              value: headline(s),
              ci: s.pass_rate_ci95,
              detail: `${s.n_scored || s.n_results} results`,
            }))}
          />
        </div>
        <div className="stack-sm">
          <h3>Latency</h3>
          <LatencyComparison agents={summaries} colors={colors} />
        </div>
      </div>
      <div className="table-wrap" style={{ marginTop: 16 }}>
        <table className="table">
          <thead>
            <tr>
              <th>Agent</th>
              <th className="right">{scored ? "Pass" : "Success"}</th>
              <th className="right">95% CI</th>
              <th className="right">Errors</th>
              <th className="right">p50</th>
              <th className="right">p95</th>
              <th className="right">p99</th>
              {summaries[0]?.consistency && <th className="right">Flaky</th>}
            </tr>
          </thead>
          <tbody>
            {summaries.map((s, i) => (
              <tr key={s.agent_id}>
                <td>
                  <span className="row" style={{ gap: 6 }}>
                    <span className="swatch" style={{ background: colors[i] }} />
                    {s.agent_name}
                  </span>
                </td>
                <td className="right num">
                  <strong>{pct(headline(s))}</strong>
                </td>
                <td className="right num faint">{s.pass_rate_ci95 ? `${pct(s.pass_rate_ci95[0], 0)}–${pct(s.pass_rate_ci95[1], 0)}` : "—"}</td>
                <td className="right num">{pct(s.error_rate)}</td>
                <td className="right num">{ms(s.scalars.latency_ms?.p50)}</td>
                <td className="right num">{ms(s.scalars.latency_ms?.p95)}</td>
                <td className="right num">{ms(s.scalars.latency_ms?.p99)}</td>
                {s.consistency && <td className="right num">{s.consistency.flaky_cases}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function TagBreakdown({ summaries, colors }: { summaries: AgentSummary[]; colors: string[] }) {
  const tags = [...new Set(summaries.flatMap((s) => Object.keys(s.by_tag ?? {})))].sort();
  if (!tags.length) return null;
  const scored = summaries.some((s) => s.pass_rate != null);
  return (
    <Card title="By tag" hint="Where each agent is strong or weak. Tags come from the dataset.">
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Tag</th>
              {summaries.map((s, i) => (
                <th key={s.agent_id}>
                  <span className="row" style={{ gap: 6 }}>
                    <span className="swatch" style={{ background: colors[i] }} />
                    {s.agent_name}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tags.map((t) => (
              <tr key={t}>
                <td>
                  <span className="tag">{t}</span>
                </td>
                {summaries.map((s, i) => {
                  const b = s.by_tag?.[t];
                  if (!b) return <td key={s.agent_id} className="faint">—</td>;
                  const rate = scored ? b.pass_rate : b.error_rate != null ? 1 - b.error_rate : null;
                  return (
                    <td key={s.agent_id}>
                      <div className="row" style={{ flexWrap: "nowrap", gap: 8 }}>
                        <div className="meter" style={{ width: 80 }}>
                          <span style={{ width: `${(rate ?? 0) * 100}%`, background: colors[i] }} />
                        </div>
                        <span className="num small">{pct(rate, 0)}</span>
                        <span className="faint small num">n={b.n}</span>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Results ─────────────────────────────────────────────────────────

function ResultDrawer({
  runId,
  row,
  onClose,
  onStep,
  position,
}: {
  runId: string;
  row: ResultRow;
  onClose: () => void;
  onStep: (dir: -1 | 1) => void;
  position: string;
}) {
  const [detail, setDetail] = useState<ResultDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let alive = true;
    setDetail(null);
    setError(null);
    api
      .result(runId, row.id)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [runId, row.id]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea")) return;
      if (e.key === "j" || e.key === "ArrowDown") onStep(1);
      if (e.key === "k" || e.key === "ArrowUp") onStep(-1);
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onStep]);
  return (
    <Drawer
      title={<span className="mono">{row.case_id}</span>}
      subtitle={
        <>
          {row.agent_name} · trial {row.trial + 1} · {position}
        </>
      }
      actions={
        <div className="row" style={{ gap: 4 }}>
          <button type="button" className="btn btn-sm btn-icon" onClick={() => onStep(-1)} aria-label="Previous result (k)" title="Previous (k)">
            <IconChevron size={14} style={{ transform: "rotate(-90deg)" }} />
          </button>
          <button type="button" className="btn btn-sm btn-icon" onClick={() => onStep(1)} aria-label="Next result (j)" title="Next (j)">
            <IconChevron size={14} style={{ transform: "rotate(90deg)" }} />
          </button>
        </div>
      }
      onClose={onClose}
    >
      <ErrorCallout error={error} />
      {detail ? <ResultView result={detail} /> : !error && <Spinner label="Loading trajectory…" />}
    </Drawer>
  );
}

function ResultsSection({ run, colors }: { run: Run; colors: Record<string, string> }) {
  const [agentId, setAgentId] = useState("");
  const [outcomes, setOutcomes] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"case" | "latency" | "outcome">("case");
  const [offset, setOffset] = useState(0);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const query = useDebounced(q, 250);
  const results = useResource(
    () => api.results(run.id, { agent_id: agentId, outcome: outcomes.join(","), q: query, sort, limit: PAGE, offset }),
    [run.id, agentId, outcomes.join(","), query, sort, offset, run.progress.completed, run.status],
  );

  const totals = useMemo(() => {
    const t: Record<string, number> = {};
    for (const s of Object.values(run.summary ?? {})) {
      if (agentId && s.agent_id !== agentId) continue;
      for (const [k, v] of Object.entries(s.outcome_counts)) t[k] = (t[k] ?? 0) + v;
    }
    return sortOutcomes(Object.entries(t));
  }, [run.summary, agentId]);

  const multiAgent = run.agents.length > 1;
  const multiTrial = (run.options.repeats ?? 1) > 1;
  const page = results.data;
  const rows = page?.items ?? [];
  const open = openIndex != null ? rows[openIndex] : null;

  const toggleOutcome = (o: string) => {
    setOffset(0);
    setOutcomes((cur) => (cur.includes(o) ? cur.filter((x) => x !== o) : [...cur, o]));
  };

  return (
    <Card
      flush
      title="Results"
      hint={isActive(run) ? "Results appear here as each case finishes." : "Click a row for the full request/response trajectory."}
      actions={
        <div className="row">
          {multiAgent && (
            <select className="select" value={agentId} onChange={(e) => (setAgentId(e.target.value), setOffset(0))} aria-label="Filter by agent" style={{ width: 180 }}>
              <option value="">All agents</option>
              {run.agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
          <select className="select" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)} aria-label="Sort results" style={{ width: 150 }}>
            <option value="case">Sort by case</option>
            <option value="latency">Slowest first</option>
            <option value="outcome">Sort by outcome</option>
          </select>
          <div className="row" style={{ position: "relative" }}>
            <IconSearch size={14} style={{ position: "absolute", left: 10, color: "var(--text-3)" }} />
            <input
              className="input"
              style={{ paddingLeft: 30, width: 220 }}
              placeholder="Search case, text, error"
              value={q}
              aria-label="Search results"
              onChange={(e) => (setQ(e.target.value), setOffset(0))}
            />
          </div>
        </div>
      }
    >
      {totals.length > 1 && (
        <div className="row" style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)" }} role="group" aria-label="Filter by outcome">
          {totals.map(([cls, n]) => (
            <button key={cls} type="button" className="chip" aria-pressed={outcomes.includes(cls)} onClick={() => toggleOutcome(cls)} title={outcomeMeta(cls).hint}>
              <span className="badge" data-tone={outcomeMeta(cls).tone} style={{ padding: 0, background: "none", height: "auto" }}>
                <span className="dot" />
              </span>
              {outcomeMeta(cls).label} <span className="count">{n}</span>
            </button>
          ))}
          {outcomes.length > 0 && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setOutcomes([])}>
              Clear
            </button>
          )}
        </div>
      )}
      <ErrorCallout error={results.error} />
      {!page ? (
        <div className="card-body">
          <Skeleton rows={6} />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState title={isActive(run) ? "Waiting for the first results…" : "No results match"}>
          {isActive(run) ? "The runner is working through the cases." : "Clear the filters to see every result."}
        </EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Case</th>
                {multiAgent && <th>Agent</th>}
                {multiTrial && <th className="right">Trial</th>}
                <th>Outcome</th>
                <th className="right">Latency</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const detail =
                  (r.outcome_class === "failed_assert" ? r.failures.join("; ") : r.error) ?? r.final_text_preview ?? "";
                return (
                  <tr key={r.id} className="clickable" aria-selected={openIndex === i} onClick={() => setOpenIndex(i)}>
                    <td className="mono small nowrap">
                      {r.case_id}
                      {r.tags.length > 0 && (
                        <div>
                          {r.tags.slice(0, 3).map((t) => (
                            <span key={t} className="tag" style={{ marginRight: 4, fontFamily: "var(--font-sans)" }}>
                              {t}
                            </span>
                          ))}
                        </div>
                      )}
                    </td>
                    {multiAgent && (
                      <td className="small nowrap">
                        <span className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                          <span className="swatch" style={{ background: colors[r.agent_id] ?? "var(--text-3)", width: 8, height: 8 }} />
                          {r.agent_name}
                        </span>
                      </td>
                    )}
                    {multiTrial && <td className="right num small">{r.trial + 1}</td>}
                    <td>
                      <OutcomeBadge outcome={r.outcome_class} />
                    </td>
                    <td className="right num small">{ms(r.latency_ms)}</td>
                    <td className={`small truncate ${r.outcome_class === "success" ? "muted" : ""}`} style={{ maxWidth: 420 }} title={detail}>
                      {detail}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {page && page.total > PAGE && (
        <div className="row-between" style={{ padding: "10px 16px", borderTop: "1px solid var(--border)" }}>
          <span className="faint small">
            {offset + 1}–{Math.min(offset + PAGE, page.total)} of {page.total}
          </span>
          <div className="row">
            <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              Previous
            </button>
            <button type="button" className="btn btn-sm" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
              Next
            </button>
          </div>
        </div>
      )}
      {open && openIndex != null && (
        <ResultDrawer
          runId={run.id}
          row={open}
          position={`${offset + openIndex + 1} of ${page?.total ?? rows.length}`}
          onClose={() => setOpenIndex(null)}
          onStep={(dir) => setOpenIndex((i) => (i == null ? i : Math.min(rows.length - 1, Math.max(0, i + dir))))}
        />
      )}
    </Card>
  );
}

// ── Page ────────────────────────────────────────────────────────────

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const now = useNow(10_000);
  const { toast, confirm } = useFeedback();
  const [acting, setActing] = useState(false);
  const { data: run, error, reload } = useResource(() => api.run(id), [id], {
    poll: (r) => (isActive(r) ? 1500 : false),
  });

  const colors = useMemo(() => Object.fromEntries((run?.agents ?? []).map((a, i) => [a.id, seriesVar(i)])), [run?.agents]);
  const summaries = useMemo(
    () => (run?.summary ? run.agents.map((a) => run.summary![a.id]).filter(Boolean) : []),
    [run],
  );

  if (error && !run) return <ErrorCallout error={error} title="Couldn't load this run" />;
  if (!run) return <Skeleton rows={8} />;

  const cancel = async () => {
    setActing(true);
    try {
      await api.cancelRun(run.id);
      toast("Run cancelled");
      reload();
    } catch (e) {
      toast(errorMessage(e), "danger");
    } finally {
      setActing(false);
    }
  };
  const rerun = async () => {
    setActing(true);
    try {
      const next = await api.rerun(run.id);
      router.push(`/runs/${next.id}`);
    } catch (e) {
      toast(errorMessage(e), "danger");
      setActing(false);
    }
  };
  const remove = async () => {
    if (!(await confirm({ title: `Delete ${runTitle(run)}?`, body: "Its results are removed permanently.", confirmLabel: "Delete run", danger: true }))) return;
    try {
      await api.deleteRun(run.id);
      toast("Run deleted");
      router.push("/runs");
    } catch (e) {
      toast(errorMessage(e), "danger");
    }
  };

  const active = isActive(run);
  const trials = run.options.repeats ?? 1;

  return (
    <>
      <PageHeader
        crumbs={[{ href: "/runs", label: "Runs" }]}
        title={
          <span className="row" style={{ gap: 10 }}>
            {runTitle(run)} <RunStatusBadge status={run.status} />
          </span>
        }
        subtitle={
          <>
            {run.dataset_id ? <Link href={`/datasets/${run.dataset_id}`}>{run.dataset_name}</Link> : <span className="mono">{run.dataset_uri}</span>}
            {" · "}
            {count(run.agents.length, "agent")}
            {trials > 1 && ` · ${trials} trials per case`}
            {run.options.score_expectations === false && " · expectations not scored"}
            {" · started "}
            <span title={absTime(run.started_at ?? run.created_at)}>{relTime(run.started_at ?? run.created_at, now)}</span>
            {run.duration_ms != null && ` · took ${ms(run.duration_ms)}`}
          </>
        }
        actions={
          <>
            {active ? (
              <button type="button" className="btn" onClick={cancel} disabled={acting}>
                <IconStop size={14} /> Cancel run
              </button>
            ) : (
              <button type="button" className="btn" onClick={rerun} disabled={acting}>
                <IconRefresh size={14} /> Run again
              </button>
            )}
            <Menu
              label="Export and more"
              items={[
                { href: api.runExportUrl(run.id, "json"), label: "Download JSON", icon: <IconDownload size={14} />, download: true },
                { href: api.runExportUrl(run.id, "csv"), label: "Download CSV", icon: <IconDownload size={14} />, download: true },
                { href: api.runExportUrl(run.id, "junit"), label: "Download JUnit XML", icon: <IconDownload size={14} />, download: true },
                "separator",
                { label: "Delete run", icon: <IconTrash size={14} />, onSelect: remove, danger: true, disabled: active },
              ]}
            />
          </>
        }
      />

      <div className="stack">
        {active && (
          <Card>
            <div className="stack-sm">
              <div className="row-between">
                <strong>{run.status === "queued" ? "Waiting for a free runner slot…" : run.progress.total ? "Evaluating" : "Loading dataset…"}</strong>
                <span className="num muted">
                  {run.progress.completed.toLocaleString()} / {run.progress.total ? run.progress.total.toLocaleString() : "?"} evaluations
                </span>
              </div>
              <ProgressBar value={run.progress.completed} total={run.status === "queued" ? 0 : run.progress.total} />
              <span className="faint small">The report fills in when the run finishes; results stream into the table below as they arrive.</span>
            </div>
          </Card>
        )}
        {run.status === "failed" && (
          <Callout tone="danger" title="This run failed">
            {run.error ?? "No error message was recorded."}
            {run.error?.toLowerCase().includes("dataset") && " Check that the dataset URL is reachable from the controller."}
          </Callout>
        )}
        {run.status === "cancelled" && <Callout tone="neutral" title="Cancelled">{run.error ?? "This run was cancelled."} Partial results are shown below.</Callout>}

        {summaries.length > 1 && <Comparison summaries={summaries} colors={summaries.map((s) => colors[s.agent_id])} />}
        {summaries.length > 0 && (
          <div className={summaries.length > 1 ? "grid-2" : "stack"} style={{ alignItems: "start" }}>
            {summaries.map((s) => (
              <AgentCard key={s.agent_id} s={s} color={colors[s.agent_id]} />
            ))}
          </div>
        )}
        {summaries.length > 0 && <TagBreakdown summaries={summaries} colors={summaries.map((s) => colors[s.agent_id])} />}

        <ResultsSection run={run} colors={colors} />
      </div>
    </>
  );
}
