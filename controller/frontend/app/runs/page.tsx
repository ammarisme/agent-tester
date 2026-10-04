"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, errorMessage, type Run, type RunStatus } from "@/lib/api";
import { absTime, ms, relTime } from "@/lib/format";
import { useDebounced, useNow, useResource } from "@/lib/hooks";
import { IconPlay, IconPlus, IconRefresh, IconRun, IconSearch, IconTrash } from "@/components/icons";
import { Menu, useFeedback } from "@/components/overlays";
import { AgentRates, runTitle } from "@/components/runs";
import { Card, EmptyState, ErrorCallout, PageHeader, ProgressBar, RunStatusBadge, Skeleton } from "@/components/ui";

const ACTIVE: RunStatus[] = ["queued", "running"];
const FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
];

export default function RunsPage() {
  const router = useRouter();
  const now = useNow(15_000);
  const { toast, confirm } = useFeedback();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const query = useDebounced(q, 250);
  const runs = useResource(() => api.runs({ status, q: query, limit: 100 }), [status, query], {
    poll: (d) => (d?.items.some((r) => ACTIVE.includes(r.status)) ? 2000 : 15000),
  });

  const rerun = async (r: Run) => {
    try {
      const next = await api.rerun(r.id);
      router.push(`/runs/${next.id}`);
    } catch (e) {
      toast(errorMessage(e), "danger");
    }
  };
  const remove = async (r: Run) => {
    if (!(await confirm({ title: `Delete ${runTitle(r)}?`, body: "Its results are removed permanently.", confirmLabel: "Delete run", danger: true }))) return;
    try {
      await api.deleteRun(r.id);
      toast("Run deleted");
      runs.reload();
    } catch (e) {
      toast(errorMessage(e), "danger");
    }
  };

  const data = runs.data;
  const newButton = (
    <Link href="/runs/new" className="btn btn-primary">
      <IconPlus size={14} /> New run
    </Link>
  );

  return (
    <>
      <PageHeader title="Runs" subtitle="Each run evaluates one or more agents against a dataset and reports distributions, not just a verdict." actions={newButton} />
      <ErrorCallout error={runs.error} />
      <Card
        flush
        title={
          <div className="row" role="group" aria-label="Filter by status">
            {FILTERS.map((f) => (
              <button key={f.value} type="button" className="chip" aria-pressed={status === f.value} onClick={() => setStatus(f.value)}>
                {f.label}
              </button>
            ))}
          </div>
        }
        actions={
          <div className="row" style={{ position: "relative" }}>
            <IconSearch size={14} style={{ position: "absolute", left: 10, color: "var(--text-3)" }} />
            <input className="input" style={{ paddingLeft: 30, width: 240 }} placeholder="Search name, dataset, agent" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search runs" />
          </div>
        }
      >
        {!data ? (
          <div className="card-body">
            <Skeleton rows={5} />
          </div>
        ) : data.items.length === 0 ? (
          status || query ? (
            <EmptyState title="No runs match">Clear the filter or search to see all runs.</EmptyState>
          ) : (
            <EmptyState icon={<IconRun size={22} />} title="No runs yet" actions={newButton}>
              Pick agents and a dataset; results stream in live as each case finishes.
            </EmptyState>
          )
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Agents · headline rate</th>
                  <th>Started</th>
                  <th className="right">Duration</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => router.push(`/runs/${r.id}`)}>
                    <td style={{ maxWidth: 280 }}>
                      <Link href={`/runs/${r.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 500, color: "var(--text)" }}>
                        {runTitle(r)}
                      </Link>
                      <div className="faint small truncate">
                        {r.dataset_name ?? r.dataset_uri ?? "—"}
                        {(r.options.repeats ?? 1) > 1 && ` · ${r.options.repeats} trials`}
                      </div>
                    </td>
                    <td>
                      <div className="stack-sm" style={{ gap: 4 }}>
                        <RunStatusBadge status={r.status} />
                        {ACTIVE.includes(r.status) && (
                          <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
                            <ProgressBar value={r.progress.completed} total={r.progress.total} />
                            <span className="faint small num nowrap">
                              {r.progress.completed}/{r.progress.total || "?"}
                            </span>
                          </div>
                        )}
                      </div>
                    </td>
                    <td>
                      <AgentRates run={r} />
                    </td>
                    <td className="faint small nowrap" title={absTime(r.created_at)}>
                      {relTime(r.created_at, now)}
                    </td>
                    <td className="right num small">{ms(r.duration_ms)}</td>
                    <td className="right" onClick={(e) => e.stopPropagation()}>
                      <Menu
                        items={[
                          { label: "Open report", icon: <IconPlay size={14} />, onSelect: () => router.push(`/runs/${r.id}`) },
                          { label: "Run again", icon: <IconRefresh size={14} />, onSelect: () => rerun(r) },
                          "separator",
                          { label: "Delete", icon: <IconTrash size={14} />, onSelect: () => remove(r), danger: true, disabled: ACTIVE.includes(r.status) },
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.total > data.items.length && <p className="faint small" style={{ padding: "10px 16px" }}>Showing the latest {data.items.length} of {data.total}. Search to narrow down.</p>}
          </div>
        )}
      </Card>
    </>
  );
}
