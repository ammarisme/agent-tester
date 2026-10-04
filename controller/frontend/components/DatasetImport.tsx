"use client";

import { useEffect, useRef, useState } from "react";
import { api, type ParseResult } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import { IconUpload } from "./icons";
import { Callout, Segmented, Spinner } from "./ui";

export const EXAMPLE_JSONL = [
  '{"id": "greeting", "input": {"message": "Hello"}, "expected": {"contains": ["Hello"]}, "tags": ["smoke"]}',
  '{"id": "refund-policy", "input": {"message": "What is your refund policy?"}, "expected": {"regex": "(?i)refund", "not_contains": ["I don\'t know"]}, "tags": ["support"]}',
  '{"id": "fast-path", "input": {"message": "ping"}, "expected": {"max_latency_ms": 2000}}',
].join("\n");

export type ImportDraft = { text: string; filename: string; result: ParseResult | null; parsing: boolean };

/**
 * Collects dataset text (upload or paste) and shows a server-side parse preview.
 * The parent decides what to do with it (create a dataset, import into one).
 */
export function DatasetImport({ onChange }: { onChange: (draft: ImportDraft) => void }) {
  const [mode, setMode] = useState<"upload" | "paste">("upload");
  const [text, setText] = useState("");
  const [filename, setFilename] = useState("cases.jsonl");
  const [result, setResult] = useState<ParseResult | null>(null);
  const [parsing, setParsing] = useState(false);
  const [drag, setDrag] = useState(false);
  const [readError, setReadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const debounced = useDebounced(text, 350);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    let alive = true;
    if (!debounced.trim()) {
      setResult(null);
      return;
    }
    setParsing(true);
    api
      .parseDataset(debounced, filename)
      .then((r) => alive && setResult(r))
      .catch((e) => alive && setResult({ format: null, count: 0, preview: [], errors: [{ message: String(e) }] }))
      .finally(() => alive && setParsing(false));
    return () => {
      alive = false;
    };
  }, [debounced, filename]);

  useEffect(() => {
    onChangeRef.current({ text, filename, result: text === debounced ? result : null, parsing: parsing || text !== debounced });
  }, [text, filename, result, parsing, debounced]);

  const readFile = async (file: File) => {
    setReadError(null);
    if (file.size > 20 * 1024 * 1024) return setReadError("File is larger than 20 MB.");
    setFilename(file.name);
    setText(await file.text());
  };

  return (
    <div className="stack">
      <div className="row-between">
        <Segmented
          label="Import source"
          value={mode}
          onChange={setMode}
          options={[
            { value: "upload", label: "Upload file" },
            { value: "paste", label: "Paste" },
          ]}
        />
        {mode === "paste" && (
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => {
              setFilename("cases.jsonl");
              setText(EXAMPLE_JSONL);
            }}
          >
            Insert example
          </button>
        )}
      </div>

      {mode === "upload" ? (
        <div
          className="dropzone"
          data-active={drag ? "true" : undefined}
          role="button"
          tabIndex={0}
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            const f = e.dataTransfer.files?.[0];
            if (f) readFile(f);
          }}
        >
          <IconUpload size={20} />
          <div style={{ marginTop: 6 }}>
            {text ? (
              <>
                <strong>{filename}</strong> · click or drop to replace
              </>
            ) : (
              <>
                <strong>Drop a file</strong> or click to choose — JSONL, JSON or CSV, up to 20 MB
              </>
            )}
          </div>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".jsonl,.ndjson,.json,.csv,application/json,text/csv"
            onChange={(e) => e.target.files?.[0] && readFile(e.target.files[0])}
          />
        </div>
      ) : (
        <textarea
          className="textarea"
          rows={8}
          spellCheck={false}
          placeholder={'One case per line:\n{"id": "c1", "input": {"message": "Hi"}, "expected": {"contains": ["Hi"]}}'}
          value={text}
          aria-label="Dataset text"
          onChange={(e) => {
            if (filename !== "pasted") setFilename("pasted");
            setText(e.target.value);
          }}
        />
      )}

      {readError && <Callout tone="danger">{readError}</Callout>}
      {parsing && text && <Spinner label="Checking…" />}
      {!parsing && result && result.errors.length > 0 && (
        <Callout tone="danger" title={`${result.errors.length} problem${result.errors.length === 1 ? "" : "s"} to fix before importing`}>
          <ul>
            {result.errors.slice(0, 10).map((e, i) => (
              <li key={i}>
                {e.line ? <strong>Line {e.line}: </strong> : null}
                {e.message}
              </li>
            ))}
          </ul>
        </Callout>
      )}
      {!parsing && result && result.errors.length === 0 && result.count > 0 && (
        <div className="stack-sm">
          <div className="row">
            <span className="badge" data-tone="good">
              <span className="dot" />
              {result.count} valid case{result.count === 1 ? "" : "s"}
            </span>
            <span className="faint small">Detected {result.format?.toUpperCase()}</span>
          </div>
          <div className="card table-wrap" style={{ maxHeight: 220, overflow: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Input</th>
                  <th>Checks</th>
                  <th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {result.preview.map((c) => (
                  <tr key={c.id}>
                    <td className="mono small">{c.id}</td>
                    <td className="mono small truncate" style={{ maxWidth: 260 }}>
                      {JSON.stringify(c.input)}
                    </td>
                    <td className="small">{c.expected ? Object.keys(c.expected).join(", ") : <span className="faint">—</span>}</td>
                    <td>{c.tags.map((t) => <span key={t} className="tag" style={{ marginRight: 4 }}>{t}</span>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.count > result.preview.length && <span className="faint small">Showing the first {result.preview.length}.</span>}
        </div>
      )}
      <details className="small">
        <summary className="muted" style={{ cursor: "pointer" }}>File format</summary>
        <div className="stack-sm" style={{ marginTop: 8 }}>
          <p className="muted">
            Each case has an <code>id</code>, an <code>input</code> (any JSON your templates read), optional <code>expected</code>{" "}
            checks and <code>tags</code>. Checks: <code>contains</code>, <code>not_contains</code>, <code>equals</code>, <code>regex</code>,{" "}
            <code>jsonpath_equals</code>, <code>max_latency_ms</code>.
          </p>
          <p className="muted">
            CSV: columns <code>id</code>, <code>expected</code> and <code>tags</code> are special; every other column becomes an input field
            (so <code>id,message</code> gives <code>input.message</code>).
          </p>
        </div>
      </details>
    </div>
  );
}

export function draftToFile(draft: ImportDraft): File {
  // Pasted text has no extension, so the server sniffs JSON / JSONL / CSV.
  return new File([draft.text], draft.filename, { type: "text/plain" });
}

export function draftReady(draft: ImportDraft | null): boolean {
  return !!draft && !draft.parsing && !!draft.result && draft.result.errors.length === 0 && draft.result.count > 0;
}
