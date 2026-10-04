"use client";

import { useId } from "react";
import type { Json } from "@/lib/api";
import { IconPlus, IconX } from "./icons";

export type ParsedJson = { ok: true; value: Json } | { ok: false; error: string };

export function parseJson(text: string, emptyValue: Json = null): ParsedJson {
  if (!text.trim()) return { ok: true, value: emptyValue };
  try {
    return { ok: true, value: JSON.parse(text) as Json };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: msg.replace(/^JSON\.parse: /, "") };
  }
}

export function toJsonText(value: unknown): string {
  return value === undefined || value === null ? "" : JSON.stringify(value, null, 2);
}

/** Monospace textarea that validates JSON as you type and can reformat it. */
export function JsonEditor({
  value,
  onChange,
  rows = 8,
  placeholder,
  error,
  id,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  placeholder?: string;
  error?: string | null;
  id?: string;
  ariaLabel?: string;
}) {
  const parsed = parseJson(value);
  const problem = error ?? (parsed.ok ? null : parsed.error);
  return (
    <div className="stack-sm" style={{ gap: 4 }}>
      <textarea
        id={id}
        aria-label={ariaLabel}
        className="textarea"
        rows={rows}
        spellCheck={false}
        value={value}
        placeholder={placeholder}
        aria-invalid={problem ? "true" : undefined}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Tab" && !e.shiftKey) {
            e.preventDefault();
            const t = e.currentTarget;
            const { selectionStart: s, selectionEnd: end } = t;
            onChange(value.slice(0, s) + "  " + value.slice(end));
            requestAnimationFrame(() => t.setSelectionRange(s + 2, s + 2));
          }
        }}
      />
      <div className="row-between small">
        <span className={problem ? "field-error" : "faint"}>{problem ?? (value.trim() ? "Valid JSON" : " ")}</span>
        {parsed.ok && value.trim() && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => onChange(JSON.stringify(parsed.value, null, 2))}>
            Format
          </button>
        )}
      </div>
    </div>
  );
}

export type KV = { key: string; value: string };

export const toKV = (obj: Record<string, unknown> | undefined | null): KV[] =>
  Object.entries(obj ?? {}).map(([key, value]) => ({ key, value: typeof value === "string" ? value : JSON.stringify(value) }));

export const fromKV = (rows: KV[]): Record<string, string> =>
  Object.fromEntries(rows.filter((r) => r.key.trim()).map((r) => [r.key.trim(), r.value]));

export function KeyValueEditor({
  rows,
  onChange,
  keyPlaceholder = "Name",
  valuePlaceholder = "Value",
  addLabel = "Add",
  suggestions,
  errors,
}: {
  rows: KV[];
  onChange: (rows: KV[]) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  addLabel?: string;
  suggestions?: string[];
  errors?: Record<string, string>;
}) {
  const listId = useId();
  const set = (i: number, patch: Partial<KV>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="stack-sm" style={{ gap: 6 }}>
      {suggestions && (
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      )}
      {rows.map((r, i) => (
        <div key={i} className="stack-sm" style={{ gap: 2 }}>
          <div className="kv-row">
            <input
              className="input mono"
              value={r.key}
              placeholder={keyPlaceholder}
              list={suggestions ? listId : undefined}
              aria-label={`${keyPlaceholder} ${i + 1}`}
              onChange={(e) => set(i, { key: e.target.value })}
            />
            <input
              className="input mono"
              value={r.value}
              placeholder={valuePlaceholder}
              aria-label={`${valuePlaceholder} ${i + 1}`}
              aria-invalid={errors?.[r.key] ? "true" : undefined}
              onChange={(e) => set(i, { value: e.target.value })}
            />
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-icon"
              aria-label={`Remove ${r.key || "row"}`}
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
            >
              <IconX size={14} />
            </button>
          </div>
          {errors?.[r.key] && <span className="field-error">{errors[r.key]}</span>}
        </div>
      ))}
      <div>
        <button type="button" className="btn btn-sm" onClick={() => onChange([...rows, { key: "", value: "" }])}>
          <IconPlus size={14} /> {addLabel}
        </button>
      </div>
    </div>
  );
}
