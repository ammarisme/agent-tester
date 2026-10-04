"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, ApiError, errorMessage, type Dataset } from "@/lib/api";
import { relTime } from "@/lib/format";
import { useNow, useResource } from "@/lib/hooks";
import { DatasetImport, draftReady, draftToFile, type ImportDraft } from "@/components/DatasetImport";
import { IconDataset, IconDownload, IconPlay, IconPlus, IconTrash } from "@/components/icons";
import { Dialog, Menu, useFeedback } from "@/components/overlays";
import { Card, EmptyState, ErrorCallout, Field, PageHeader, Segmented, Skeleton } from "@/components/ui";

function NewDatasetDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [source, setSource] = useState<"local" | "uri">("local");
  const [uri, setUri] = useState("");
  const [draft, setDraft] = useState<ImportDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const canSubmit = name.trim() && (source === "uri" ? /^https?:\/\//.test(uri.trim()) : draftReady(draft));

  const submit = async () => {
    setBusy(true);
    setError(null);
    let created: Dataset | null = null;
    try {
      if (source === "uri") {
        created = await api.createDataset({ name: name.trim(), description, source_type: "uri", uri: uri.trim() });
      } else {
        created = await api.createDataset({ name: name.trim(), description, source_type: "local" });
        await api.importDataset(created.id, draftToFile(draft!), "replace");
      }
      router.push(`/datasets/${created.id}`);
    } catch (e) {
      // Don't leave an empty dataset behind if the import step failed.
      if (created && source === "local") await api.deleteDataset(created.id).catch(() => undefined);
      setError(e);
      setBusy(false);
    }
  };

  return (
    <Dialog
      wide
      title="New dataset"
      description="A dataset is a list of cases: an input to send and, optionally, checks on the answer."
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" disabled={!canSubmit || busy} onClick={submit}>
            {busy && <span className="spinner" />}
            {source === "uri" ? "Register dataset" : draft?.result?.count ? `Create with ${draft.result.count} cases` : "Create dataset"}
          </button>
        </>
      }
    >
      <div className="stack">
        <ErrorCallout error={error} />
        <div className="grid-2">
          <Field label="Name" htmlFor="ds-name">
            <input id="ds-name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Support FAQ — regression set" data-autofocus />
          </Field>
          <Field label="Description" optional htmlFor="ds-desc">
            <input id="ds-desc" className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
          </Field>
        </div>
        <Field label="Where do the cases live?">
          <Segmented
            label="Dataset source"
            value={source}
            onChange={setSource}
            options={[
              { value: "local", label: "Store them here" },
              { value: "uri", label: "Fetch from a URL at run time" },
            ]}
          />
        </Field>
        {source === "local" ? (
          <DatasetImport onChange={setDraft} />
        ) : (
          <Field
            label="Dataset URL"
            hint="JSONL, JSON or CSV over http(s). Fetched fresh on every run, so the source of truth stays in your repo or bucket."
            error={error instanceof ApiError ? error.fieldErrors()["uri"] : undefined}
          >
            <input className="input mono" value={uri} onChange={(e) => setUri(e.target.value)} placeholder="https://raw.githubusercontent.com/org/repo/main/evals/cases.jsonl" />
          </Field>
        )}
      </div>
    </Dialog>
  );
}

export default function DatasetsPage() {
  const router = useRouter();
  const now = useNow();
  const { toast, confirm } = useFeedback();
  const [creating, setCreating] = useState(false);
  const { data, error, loading, reload } = useResource(api.datasets, []);

  const remove = async (d: Dataset) => {
    const ok = await confirm({
      title: `Delete “${d.name}”?`,
      body: `Its ${d.case_count} stored cases are removed. Past runs keep their results.`,
      confirmLabel: "Delete dataset",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteDataset(d.id);
      toast("Dataset deleted");
      reload();
    } catch (e) {
      toast(errorMessage(e), "danger");
    }
  };

  const newButton = (
    <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
      <IconPlus size={14} /> New dataset
    </button>
  );

  return (
    <>
      <PageHeader
        title="Datasets"
        subtitle="Evaluation sets. Store cases here, or register a URL so the runner fetches the latest version each time."
        actions={newButton}
      />
      <ErrorCallout error={error} />
      <Card flush>
        {loading && !data ? (
          <div className="card-body">
            <Skeleton rows={4} />
          </div>
        ) : data && data.length === 0 ? (
          <EmptyState icon={<IconDataset size={22} />} title="No datasets yet" actions={newButton}>
            Upload a JSONL, JSON or CSV file, paste cases, or point at a URL. Every case is checked before it&apos;s saved.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Source</th>
                  <th className="right">Cases</th>
                  <th>Tags</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data?.map((d) => (
                  <tr key={d.id} className="clickable" onClick={() => router.push(`/datasets/${d.id}`)}>
                    <td style={{ maxWidth: 300 }}>
                      <Link href={`/datasets/${d.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 500, color: "var(--text)" }}>
                        {d.name}
                      </Link>
                      {d.description && <div className="faint small truncate">{d.description}</div>}
                    </td>
                    <td className="small">
                      {d.source_type === "uri" ? (
                        <span className="mono truncate" style={{ display: "inline-block", maxWidth: 280 }} title={d.uri ?? ""}>
                          {d.uri}
                        </span>
                      ) : (
                        <span className="muted">Stored</span>
                      )}
                    </td>
                    <td className="right num">{d.source_type === "uri" ? <span className="faint">at run time</span> : d.case_count}</td>
                    <td>
                      {d.tags.slice(0, 4).map((t) => (
                        <span key={t} className="tag" style={{ marginRight: 4 }}>
                          {t}
                        </span>
                      ))}
                      {d.tags.length > 4 && <span className="faint small">+{d.tags.length - 4}</span>}
                    </td>
                    <td className="faint small nowrap">{relTime(d.updated_at ?? d.created_at, now)}</td>
                    <td className="right" onClick={(e) => e.stopPropagation()}>
                      <Menu
                        items={[
                          { label: "Run evaluation", icon: <IconPlay size={14} />, onSelect: () => router.push(`/runs/new?dataset=${d.id}`) },
                          { href: api.datasetExportUrl(d.id), label: "Download JSONL", icon: <IconDownload size={14} />, download: true },
                          "separator",
                          { label: "Delete", icon: <IconTrash size={14} />, onSelect: () => remove(d), danger: true },
                        ]}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {creating && <NewDatasetDialog onClose={() => setCreating(false)} />}
    </>
  );
}
