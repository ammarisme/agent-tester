"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api, type Agent, type Dataset } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { IconPlay } from "@/components/icons";
import { Callout, Card, ErrorCallout, Field, PageHeader, Segmented, Skeleton } from "@/components/ui";

function AgentPicker({ agents, selected, onToggle }: { agents: Agent[]; selected: string[]; onToggle: (id: string) => void }) {
  const enabled = agents.filter((a) => a.enabled);
  const disabled = agents.length - enabled.length;
  if (!agents.length)
    return (
      <Callout tone="info" title="You need an agent first">
        <Link href="/agents/new">Create an agent</Link> — or load the demo from the <Link href="/">overview</Link>.
      </Callout>
    );
  return (
    <div className="stack-sm">
      <div className="grid-auto">
        {enabled.map((a) => {
          const on = selected.includes(a.id);
          return (
            <button key={a.id} type="button" role="checkbox" aria-checked={on} className="choice" onClick={() => onToggle(a.id)}>
              <span className="row" style={{ flexWrap: "nowrap" }}>
                <input type="checkbox" checked={on} readOnly tabIndex={-1} aria-hidden style={{ accentColor: "var(--accent)" }} />
                <strong className="truncate">{a.name}</strong>
              </span>
              <span className="mono faint small truncate">
                {a.contract.invoke.method} {a.contract.invoke.url}
              </span>
            </button>
          );
        })}
      </div>
      {disabled > 0 && <span className="faint small">{disabled} disabled agent{disabled === 1 ? " is" : "s are"} hidden.</span>}
    </div>
  );
}

function NewRun() {
  const router = useRouter();
  const params = useSearchParams();
  const agents = useResource(api.agents, []);
  const datasets = useResource(api.datasets, []);

  const [selected, setSelected] = useState<string[]>([]);
  const [source, setSource] = useState<"stored" | "url">("stored");
  const [datasetId, setDatasetId] = useState("");
  const [datasetUri, setDatasetUri] = useState("");
  const [name, setName] = useState("");
  const [repeats, setRepeats] = useState(1);
  const [concurrency, setConcurrency] = useState(8);
  const [score, setScore] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Apply ?agent= / ?dataset= preselection once data arrives.
  useEffect(() => {
    const a = params.get("agent");
    if (agents.data) setSelected(a ? [a] : agents.data.filter((x) => x.enabled).length === 1 ? [agents.data.find((x) => x.enabled)!.id] : []);
  }, [agents.data, params]);
  useEffect(() => {
    const d = params.get("dataset");
    if (datasets.data) setDatasetId(d ?? (datasets.data.length === 1 ? datasets.data[0].id : ""));
  }, [datasets.data, params]);

  const dataset: Dataset | undefined = datasets.data?.find((d) => d.id === datasetId);
  const nCases = source === "stored" && dataset?.source_type === "local" ? dataset.case_count : null;
  const total = nCases != null ? selected.length * nCases * repeats : null;
  const datasetOk = source === "stored" ? !!dataset && (dataset.source_type === "uri" || dataset.case_count > 0) : /^https?:\/\//.test(datasetUri.trim());
  const ready = selected.length > 0 && datasetOk && !busy;

  const blockers = useMemo(() => {
    const out: string[] = [];
    if (!selected.length) out.push("Select at least one agent.");
    if (source === "stored" && !dataset) out.push("Choose a dataset.");
    if (source === "stored" && dataset?.source_type === "local" && dataset.case_count === 0) out.push("The selected dataset has no cases.");
    if (source === "url" && !/^https?:\/\//.test(datasetUri.trim())) out.push("Enter an http(s) dataset URL.");
    return out;
  }, [selected, source, dataset, datasetUri]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const run = await api.createRun({
        name: name.trim() || null,
        agent_ids: selected,
        dataset_id: source === "stored" ? datasetId : null,
        dataset_uri: source === "url" ? datasetUri.trim() : null,
        options: { repeats, concurrency, score_expectations: score },
      });
      router.push(`/runs/${run.id}`);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };

  if (!agents.data || !datasets.data) return <Skeleton rows={6} />;

  return (
    <div className="split-main">
      <div className="stack">
        <ErrorCallout error={error ?? agents.error ?? datasets.error} />
        <Card title="1 · Agents" hint="Pick several to compare them on identical cases.">
          <AgentPicker agents={agents.data} selected={selected} onToggle={(id) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))} />
        </Card>

        <Card
          title="2 · Dataset"
          actions={
            <Segmented
              label="Dataset source"
              value={source}
              onChange={setSource}
              options={[
                { value: "stored", label: "Saved dataset" },
                { value: "url", label: "One-off URL" },
              ]}
            />
          }
        >
          {source === "stored" ? (
            datasets.data.length === 0 ? (
              <Callout tone="info" title="No datasets yet">
                <Link href="/datasets">Create a dataset</Link>, or switch to a one-off URL.
              </Callout>
            ) : (
              <Field label="Dataset" hint={dataset?.description || undefined}>
                <select className="select" value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
                  <option value="">Choose a dataset…</option>
                  {datasets.data.map((d) => (
                    <option key={d.id} value={d.id} disabled={d.source_type === "local" && d.case_count === 0}>
                      {d.name} — {d.source_type === "uri" ? "fetched at run time" : `${d.case_count} cases`}
                    </option>
                  ))}
                </select>
              </Field>
            )
          ) : (
            <Field label="Dataset URL" hint="JSONL, JSON or CSV. Fetched once when the run starts.">
              <input className="input mono" value={datasetUri} onChange={(e) => setDatasetUri(e.target.value)} placeholder="https://…/cases.jsonl" />
            </Field>
          )}
        </Card>

        <Card title="3 · Options">
          <div className="stack">
            <div className="grid-2">
              <Field label="Trials per case" hint="Agents are non-deterministic. 3–5 trials show how consistent each answer is.">
                <input className="input" type="number" min={1} max={100} value={repeats} onChange={(e) => setRepeats(Math.max(1, Math.min(100, Number(e.target.value) || 1)))} />
              </Field>
              <Field label="Concurrency" hint="Requests in flight at once, across all agents.">
                <input className="input" type="number" min={1} max={256} value={concurrency} onChange={(e) => setConcurrency(Math.max(1, Math.min(256, Number(e.target.value) || 1)))} />
              </Field>
            </div>
            <label className="check">
              <input type="checkbox" checked={score} onChange={(e) => setScore(e.target.checked)} />
              <span>
                Check expectations
                <span className="field-hint" style={{ display: "block" }}>
                  Score each answer against the case&apos;s <code>expected</code> block. Turn off to measure only reachability and latency.
                </span>
              </span>
            </label>
            <Field label="Run name" optional hint="Helps you find it later, e.g. “prompt v12 vs v11”.">
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
          </div>
        </Card>
      </div>

      <div className="sticky-side">
        <Card title="Summary">
          <div className="stack">
            <dl className="stack-sm" style={{ margin: 0 }}>
              <div className="row-between">
                <dt className="muted">Agents</dt>
                <dd style={{ margin: 0 }}>{selected.length}</dd>
              </div>
              <div className="row-between">
                <dt className="muted">Cases</dt>
                <dd style={{ margin: 0 }}>{nCases ?? (datasetOk ? "at run time" : "—")}</dd>
              </div>
              <div className="row-between">
                <dt className="muted">Trials</dt>
                <dd style={{ margin: 0 }}>{repeats}</dd>
              </div>
              <div className="row-between" style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                <dt style={{ fontWeight: 600 }}>Requests</dt>
                <dd style={{ margin: 0, fontWeight: 600 }} className="num">
                  {total != null ? total.toLocaleString() : "—"}
                </dd>
              </div>
            </dl>
            {total != null && total > 2000 && (
              <Callout tone="warning">That&apos;s a lot of requests. Make sure the agent&apos;s rate limits and costs allow it.</Callout>
            )}
            <button type="button" className="btn btn-primary" onClick={start} disabled={!ready} style={{ height: 38 }}>
              {busy ? <span className="spinner" /> : <IconPlay size={14} />} Start run
            </button>
            {blockers.length > 0 && (
              <ul className="faint small" style={{ margin: 0, paddingLeft: 18 }}>
                {blockers.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}

export default function NewRunPage() {
  return (
    <>
      <PageHeader title="New run" crumbs={[{ href: "/runs", label: "Runs" }]} />
      <Suspense fallback={<Skeleton rows={6} />}>
        <NewRun />
      </Suspense>
    </>
  );
}
