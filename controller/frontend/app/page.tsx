"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { ms, relTime } from "@/lib/format";
import { useNow, useResource } from "@/lib/hooks";
import { IconAgent, IconBolt, IconCheck, IconDataset, IconPlay, IconRun } from "@/components/icons";
import { useFeedback } from "@/components/overlays";
import { AgentRates, runTitle } from "@/components/runs";
import { Card, CodeBlock, ErrorCallout, PageHeader, RunStatusBadge, Skeleton } from "@/components/ui";

const CI_SNIPPET = `pip install ./tester
agent-tester run \\
  --agent agents/support-bot.json \\
  --dataset evals/support.jsonl \\
  --repeats 3 \\
  --fail-under 0.9 --max-error-rate 0.05 \\
  --junit reports/agent-eval.xml`;

function useDemo() {
  const router = useRouter();
  const { toast } = useFeedback();
  const [busy, setBusy] = useState(false);
  const start = async () => {
    setBusy(true);
    try {
      const demo = await api.demo();
      const run = await api.createRun({
        name: "Demo: echo vs flaky",
        agent_ids: demo.agent_ids,
        dataset_id: demo.dataset_id,
        options: { repeats: 3, concurrency: 8, score_expectations: true },
      });
      router.push(`/runs/${run.id}`);
    } catch (e) {
      toast(errorMessage(e), "danger");
      setBusy(false);
    }
  };
  return { start, busy };
}

function Welcome() {
  const demo = useDemo();
  return (
    <div className="stack" style={{ gap: 28, maxWidth: 880 }}>
      <div className="stack-sm" style={{ gap: 12, paddingTop: 12 }}>
        <span className="brand-mark" style={{ width: 40, height: 40, borderRadius: 10 }}>
          <IconBolt size={20} />
        </span>
        <h1 style={{ fontSize: 28 }}>Evaluate agents the way you evaluate models</h1>
        <p className="muted" style={{ fontSize: 15, maxWidth: "62ch" }}>
          Agents are non-deterministic, so one pass/fail answer hides what matters. Agent Tester runs a dataset against any HTTP agent — several
          times if you like — records every request and response, and reports pass rates with confidence intervals, latency percentiles and
          how consistent each answer is.
        </p>
        <div className="row" style={{ marginTop: 8 }}>
          <button type="button" className="btn btn-primary" onClick={demo.start} disabled={demo.busy} style={{ height: 38, padding: "0 16px" }}>
            {demo.busy ? <span className="spinner" /> : <IconPlay size={14} />} Run the 30-second demo
          </button>
          <Link href="/agents/new" className="btn" style={{ height: 38, padding: "0 16px" }}>
            Connect your own agent
          </Link>
        </div>
        <p className="faint small">The demo compares two bundled mock agents — one reliable, one flaky — on six cases with three trials each. No credentials needed.</p>
      </div>

      <div className="grid-3">
        {[
          { icon: <IconAgent />, title: "1. Describe your agent", body: "An HTTP contract: URL, headers, a body template and which response field to score. Async submit-and-poll APIs work too." },
          { icon: <IconDataset />, title: "2. Add cases", body: "Upload JSONL, JSON or CSV. Each case has an input and optional checks: contains, regex, JSONPath, latency budget." },
          { icon: <IconRun />, title: "3. Read distributions", body: "Compare agents side by side, find flaky cases, and open any result to see the exact request and response." },
        ].map((s) => (
          <div key={s.title} className="card card-body stack-sm">
            <span className="empty-icon" style={{ width: 32, height: 32, borderRadius: 8 }}>
              {s.icon}
            </span>
            <h2>{s.title}</h2>
            <p className="muted small">{s.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Checklist({ agents, datasets, runs }: { agents: number; datasets: number; runs: number }) {
  const steps = [
    { done: agents > 0, label: "Add an agent", hint: "Start from a template and send a test request.", href: "/agents/new", cta: "New agent" },
    { done: datasets > 0, label: "Add a dataset", hint: "Upload or paste cases with optional checks.", href: "/datasets", cta: "New dataset" },
    { done: runs > 0, label: "Run an evaluation", hint: "Compare agents with several trials per case.", href: "/runs/new", cta: "New run" },
  ];
  if (steps.every((s) => s.done)) return null;
  return (
    <Card title="Get set up" hint={`${steps.filter((s) => s.done).length} of ${steps.length} done`} flush>
      <ul className="checklist">
        {steps.map((s) => (
          <li key={s.label}>
            <span className="check-circle" data-done={s.done ? "true" : undefined}>
              {s.done && <IconCheck size={13} />}
            </span>
            <div className="grow">
              <div style={{ fontWeight: 500, textDecoration: s.done ? "line-through" : undefined, color: s.done ? "var(--text-3)" : undefined }}>{s.label}</div>
              {!s.done && <div className="faint small">{s.hint}</div>}
            </div>
            {!s.done && (
              <Link href={s.href} className="btn btn-sm">
                {s.cta}
              </Link>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function OverviewPage() {
  const now = useNow();
  const demo = useDemo();
  const agents = useResource(api.agents, []);
  const datasets = useResource(api.datasets, []);
  const runs = useResource(() => api.runs({ limit: 8 }), [], {
    poll: (d) => (d?.items.some((r) => r.status === "running" || r.status === "queued") ? 2500 : false),
  });
  const error = agents.error ?? datasets.error ?? runs.error;

  if (error) return <ErrorCallout error={error} title="Can't reach the Agent Tester API" />;
  if (!agents.data || !datasets.data || !runs.data) return <Skeleton rows={6} />;

  const nAgents = agents.data.length;
  const nDatasets = datasets.data.length;
  const nRuns = runs.data.total;
  if (!nAgents && !nDatasets && !nRuns) return <Welcome />;

  return (
    <>
      <PageHeader
        title="Overview"
        actions={
          <>
            <button type="button" className="btn" onClick={demo.start} disabled={demo.busy}>
              {demo.busy && <span className="spinner" />} Run demo
            </button>
            <Link href="/runs/new" className="btn btn-primary">
              <IconPlay size={14} /> New run
            </Link>
          </>
        }
      />
      <div className="stack">
        <div className="stats">
          <Link href="/agents" className="stat" style={{ color: "inherit", textDecoration: "none" }}>
            <div className="stat-label">Agents</div>
            <div className="stat-value">{nAgents}</div>
            <div className="stat-sub">{agents.data.filter((a) => a.enabled).length} enabled</div>
          </Link>
          <Link href="/datasets" className="stat" style={{ color: "inherit", textDecoration: "none" }}>
            <div className="stat-label">Datasets</div>
            <div className="stat-value">{nDatasets}</div>
            <div className="stat-sub">{datasets.data.reduce((n, d) => n + d.case_count, 0).toLocaleString()} stored cases</div>
          </Link>
          <Link href="/runs" className="stat" style={{ color: "inherit", textDecoration: "none" }}>
            <div className="stat-label">Runs</div>
            <div className="stat-value">{nRuns}</div>
            <div className="stat-sub">{runs.data.items.filter((r) => r.status === "running" || r.status === "queued").length} in progress</div>
          </Link>
        </div>

        <Checklist agents={nAgents} datasets={nDatasets} runs={nRuns} />

        <div className="split-wide">
          <Card
            title="Recent runs"
            flush
            actions={
              <Link href="/runs" className="btn btn-sm btn-ghost">
                View all
              </Link>
            }
          >
            {runs.data.items.length === 0 ? (
              <p className="muted" style={{ padding: 16 }}>
                No runs yet. <Link href="/runs/new">Start one</Link>.
              </p>
            ) : (
              <table className="table">
                <tbody>
                  {runs.data.items.map((r) => (
                    <tr key={r.id}>
                      <td>
                        <Link href={`/runs/${r.id}`} style={{ fontWeight: 500, color: "var(--text)" }}>
                          {runTitle(r)}
                        </Link>
                        <div className="faint small">
                          {relTime(r.created_at, now)}
                          {r.duration_ms != null && ` · ${ms(r.duration_ms)}`}
                        </div>
                      </td>
                      <td>
                        <RunStatusBadge status={r.status} />
                      </td>
                      <td>
                        <AgentRates run={r} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Gate releases in CI" hint="The same engine runs headless. Exit code 1 when a gate fails; JUnit XML for your CI's test view.">
            <CodeBlock value={CI_SNIPPET} wrap={false} />
          </Card>
        </div>
      </div>
    </>
  );
}
