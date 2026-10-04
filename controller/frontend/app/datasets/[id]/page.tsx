"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { count } from "@/lib/format";
import { useDebounced, useResource } from "@/lib/hooks";
import { DatasetImport, draftReady, draftToFile, type ImportDraft } from "@/components/DatasetImport";
import { IconChevron, IconDownload, IconPlay, IconSearch, IconTrash, IconUpload } from "@/components/icons";
import { Dialog, Menu, useFeedback } from "@/components/overlays";
import { Card, CodeBlock, EmptyState, ErrorCallout, PageHeader, Segmented, Skeleton } from "@/components/ui";

const PAGE = 50;

function ImportDialog({ datasetId, onClose, onDone }: { datasetId: string; onClose: () => void; onDone: () => void }) {
  const [draft, setDraft] = useState<ImportDraft | null>(null);
  const [mode, setMode] = useState<"append" | "replace">("append");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const { toast } = useFeedback();
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const ds = await api.importDataset(datasetId, draftToFile(draft!), mode);
      toast(`Dataset now has ${count(ds.case_count, "case")}`);
      onDone();
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Dialog
      wide
      title="Import cases"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={`btn ${mode === "replace" ? "btn-danger-solid" : "btn-primary"}`} disabled={!draftReady(draft) || busy} onClick={submit}>
            {busy && <span className="spinner" />}
            {mode === "replace" ? "Replace all cases" : "Add cases"}
          </button>
        </>
      }
    >
      <div className="stack">
        <ErrorCallout error={error} />
        <Segmented
          label="Import mode"
          value={mode}
          onChange={setMode}
          options={[
            { value: "append", label: "Add to existing" },
            { value: "replace", label: "Replace existing" },
          ]}
        />
        <DatasetImport onChange={setDraft} />
      </div>
    </Dialog>
  );
}

export default function DatasetPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { toast, confirm } = useFeedback();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const query = useDebounced(q, 250);

  const ds = useResource(() => api.dataset(id), [id]);
  const cases = useResource(() => api.cases(id, { q: query, limit: PAGE, offset }), [id, query, offset]);
  const d = ds.data;

  const remove = async () => {
    if (!d) return;
    const ok = await confirm({ title: `Delete “${d.name}”?`, body: "Past runs keep their results.", confirmLabel: "Delete dataset", danger: true });
    if (!ok) return;
    try {
      await api.deleteDataset(id);
      toast("Dataset deleted");
      router.push("/datasets");
    } catch (e) {
      toast(errorMessage(e), "danger");
    }
  };

  const page = cases.data;
  return (
    <>
      <PageHeader
        crumbs={[{ href: "/datasets", label: "Datasets" }]}
        title={d?.name ?? "Dataset"}
        subtitle={
          d &&
          (d.source_type === "uri" ? (
            <>
              Fetched at run time from <span className="mono">{d.uri}</span>. The preview below is live.
            </>
          ) : (
            d.description || count(d.case_count, "case")
          ))
        }
        actions={
          d && (
            <>
              {d.source_type === "local" && (
                <button type="button" className="btn" onClick={() => setImporting(true)}>
                  <IconUpload size={14} /> Import
                </button>
              )}
              <Link href={`/runs/new?dataset=${id}`} className="btn btn-primary">
                <IconPlay size={14} /> Run evaluation
              </Link>
              <Menu
                items={[
                  { href: api.datasetExportUrl(id), label: "Download JSONL", icon: <IconDownload size={14} />, download: true },
                  "separator",
                  { label: "Delete dataset", icon: <IconTrash size={14} />, onSelect: remove, danger: true },
                ]}
              />
            </>
          )
        }
      />
      <ErrorCallout error={ds.error} />

      <Card
        flush
        title={page ? `${count(page.total, "case")}${query ? " matching" : ""}` : "Cases"}
        actions={
          <div className="row" style={{ position: "relative" }}>
            <IconSearch size={14} style={{ position: "absolute", left: 10, color: "var(--text-3)" }} />
            <input
              className="input"
              style={{ paddingLeft: 30, width: 240 }}
              placeholder="Search id, input or tags"
              value={q}
              aria-label="Search cases"
              onChange={(e) => {
                setQ(e.target.value);
                setOffset(0);
              }}
            />
          </div>
        }
      >
        <ErrorCallout error={cases.error} />
        {!page ? (
          <div className="card-body">
            <Skeleton rows={5} />
          </div>
        ) : page.total === 0 ? (
          <EmptyState
            title={query ? "No cases match" : "This dataset is empty"}
            actions={
              !query && d?.source_type === "local" ? (
                <button type="button" className="btn btn-primary" onClick={() => setImporting(true)}>
                  <IconUpload size={14} /> Import cases
                </button>
              ) : undefined
            }
          >
            {query ? "Try a different search." : "Import a JSONL, JSON or CSV file to add cases."}
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th style={{ width: 28 }} />
                  <th>ID</th>
                  <th>Input</th>
                  <th>Checks</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((c) => {
                  const open = expanded === c.id;
                  return (
                    <Fragment key={c.id}>
                      <tr className="clickable" aria-expanded={open} onClick={() => setExpanded(open ? null : c.id)}>
                        <td>
                          <IconChevron size={14} style={{ transform: open ? "rotate(90deg)" : undefined, color: "var(--text-3)" }} />
                        </td>
                        <td className="mono small nowrap">{c.id}</td>
                        <td className="mono small truncate" style={{ maxWidth: 420 }}>
                          {typeof c.input === "string" ? c.input : JSON.stringify(c.input)}
                        </td>
                        <td className="small">{c.expected ? Object.keys(c.expected).join(", ") : <span className="faint">none</span>}</td>
                        <td>
                          {c.tags.map((t) => (
                            <span key={t} className="tag" style={{ marginRight: 4 }}>
                              {t}
                            </span>
                          ))}
                        </td>
                      </tr>
                      {open && (
                        <tr>
                          <td />
                          <td colSpan={4}>
                            <div className="grid-2" style={{ padding: "4px 0 8px" }}>
                              <div className="stack-sm">
                                <h3>Input</h3>
                                <CodeBlock value={c.input} />
                              </div>
                              <div className="stack-sm">
                                <h3>Expected</h3>
                                {c.expected ? <CodeBlock value={c.expected} /> : <p className="faint small">No checks: scored on outcome only.</p>}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
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
      </Card>
      {importing && (
        <ImportDialog
          datasetId={id}
          onClose={() => setImporting(false)}
          onDone={() => {
            setImporting(false);
            ds.reload();
            cases.reload();
          }}
        />
      )}
    </>
  );
}
