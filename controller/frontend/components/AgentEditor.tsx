"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiError,
  errorMessage,
  type Agent,
  type Contract,
  type Expectations,
  type HttpMethod,
  type Json,
  type TestResult,
} from "@/lib/api";
import { fromKV, JsonEditor, KeyValueEditor, parseJson, toJsonText, toKV, type KV } from "./editors";
import { IconPlay } from "./icons";
import { useFeedback } from "./overlays";
import { ResultView } from "./ResultView";
import { Callout, Card, ErrorCallout, Field, Segmented, Spinner, Tabs } from "./ui";

type BodyMode = "json" | "passthrough" | "none";

type FormState = {
  name: string;
  description: string;
  enabled: boolean;
  method: HttpMethod;
  url: string;
  headers: KV[];
  bodyMode: BodyMode;
  bodyText: string;
  timeout: string;
  extract: KV[];
  pollEnabled: boolean;
  pollMethod: "GET" | "POST";
  pollUrl: string;
  pollHeaders: KV[];
  pollInterval: string;
  pollTimeout: string;
  doneWhen: string;
  failedWhen: string;
  pollExtract: KV[];
  params: KV[];
};

const PASSTHROUGH = "{{ input }}";

export const BLANK_CONTRACT: Contract = {
  invoke: {
    method: "POST",
    url: "https://agent.example.com/v1/chat",
    headers: { "Content-Type": "application/json" },
    body_template: { message: "{{ input.message }}" },
    timeout_s: 60,
  },
  poll: null,
  extract: { final_text: "$.reply" },
};

function toForm(a: Pick<Agent, "name" | "description" | "enabled" | "contract" | "params">): FormState {
  const c = a.contract;
  const body = c.invoke.body_template;
  const bodyMode: BodyMode =
    body === undefined || body === null ? "none" : typeof body === "string" && body.trim() === PASSTHROUGH ? "passthrough" : "json";
  const p = c.poll;
  return {
    name: a.name,
    description: a.description ?? "",
    enabled: a.enabled,
    method: c.invoke.method ?? "POST",
    url: c.invoke.url ?? "",
    headers: toKV(c.invoke.headers),
    bodyMode,
    bodyText: bodyMode === "json" ? toJsonText(body) : '{\n  "message": "{{ input.message }}"\n}',
    timeout: String(c.invoke.timeout_s ?? 60),
    extract: toKV(c.extract),
    pollEnabled: !!p,
    pollMethod: p?.method ?? "GET",
    pollUrl: p?.url_template ?? "",
    pollHeaders: toKV(p?.headers),
    pollInterval: String(p?.interval_s ?? 2),
    pollTimeout: String(p?.timeout_s ?? 600),
    doneWhen: p?.done_when ?? "status in ['COMPLETED','FAILED']",
    failedWhen: p?.failed_when ?? "status in ['FAILED','ERROR','CANCELLED']",
    pollExtract: toKV(p?.extract ?? { final_text: "$.result" }),
    params: toKV(a.params),
  };
}

function num(v: string, fallback: number): number {
  const n = Number(v);
  return Number.isFinite(n) && v.trim() !== "" ? n : fallback;
}

function paramsFromKV(rows: KV[]): Record<string, Json> {
  const out: Record<string, Json> = {};
  for (const r of rows) {
    if (!r.key.trim()) continue;
    const parsed = parseJson(r.value);
    out[r.key.trim()] = parsed.ok && r.value.trim() !== "" && typeof parsed.value !== "string" ? parsed.value : r.value;
  }
  return out;
}

/** Returns the contract, or an error string if the body JSON is invalid. */
function fromForm(f: FormState): { contract: Contract; params: Record<string, Json> } | { error: string } {
  let body: Json = null;
  if (f.bodyMode === "passthrough") body = PASSTHROUGH;
  if (f.bodyMode === "json") {
    const parsed = parseJson(f.bodyText);
    if (!parsed.ok) return { error: `Request body is not valid JSON: ${parsed.error}` };
    body = parsed.value;
  }
  const contract: Contract = {
    invoke: {
      method: f.method,
      url: f.url.trim(),
      headers: fromKV(f.headers),
      body_template: body,
      timeout_s: num(f.timeout, 60),
    },
    poll: f.pollEnabled
      ? {
          method: f.pollMethod,
          url_template: f.pollUrl.trim(),
          headers: fromKV(f.pollHeaders),
          interval_s: num(f.pollInterval, 2),
          timeout_s: num(f.pollTimeout, 600),
          done_when: f.doneWhen.trim(),
          failed_when: f.failedWhen.trim() || null,
          extract: fromKV(f.pollExtract),
        }
      : null,
    extract: fromKV(f.extract),
  };
  return { contract, params: paramsFromKV(f.params) };
}

const HEADER_SUGGESTIONS = ["Content-Type", "Authorization", "Accept", "X-API-Key", "X-Request-ID"];

function TemplateHelp() {
  return (
    <details className="small">
      <summary className="muted" style={{ cursor: "pointer" }}>Template reference</summary>
      <table className="table" style={{ marginTop: 8 }}>
        <tbody>
          {[
            ["{{ input.message }}", "A field of the case's input"],
            ["{{ input }}", "The whole input, keeping its JSON type"],
            ["{{ agent.params.base_url }}", "A parameter of this agent"],
            ["{{ extracted.job_id }}", "A field extracted from the invoke response (poll only)"],
            ["{{ uuid() }} · {{ trial }}", "A fresh UUID · the trial number (0-based)"],
            ["${AGENT_API_KEY}", "An environment variable on the runner — use for secrets"],
          ].map(([t, d]) => (
            <tr key={t}>
              <td className="mono nowrap">{t}</td>
              <td className="muted">{d}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function TestPanel({ build }: { build: () => ReturnType<typeof fromForm> }) {
  const [inputText, setInputText] = useState('{\n  "message": "Hello, agent"\n}');
  const [expectedText, setExpectedText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<unknown>(null);

  const send = async () => {
    setError(null);
    const built = build();
    if ("error" in built) return setError(new ApiError(400, built.error));
    const input = parseJson(inputText);
    const expected = parseJson(expectedText);
    if (!input.ok) return setError(new ApiError(400, `Input is not valid JSON: ${input.error}`));
    if (!expected.ok) return setError(new ApiError(400, `Expected is not valid JSON: ${expected.error}`));
    setBusy(true);
    try {
      setResult(
        await api.testAgent({
          ...built,
          input: input.value,
          expected: (expected.value as Expectations | null) ?? null,
        }),
      );
    } catch (e) {
      setResult(null);
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Test request" hint="Sends one real request with the settings on the left. Nothing is saved.">
      <div
        className="stack"
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            send();
          }
        }}
      >
        <Field label="Case input" hint="Available to templates as input.*">
          <JsonEditor value={inputText} onChange={setInputText} rows={4} ariaLabel="Case input" />
        </Field>
        <Field label="Expected" optional hint='e.g. {"contains": ["Hello"]}'>
          <JsonEditor value={expectedText} onChange={setExpectedText} rows={2} placeholder='{"contains": ["Hello"]}' ariaLabel="Expected" />
        </Field>
        <div className="row-between">
          <span className="faint small">
            <kbd>⌘</kbd> <kbd>Enter</kbd> to send
          </span>
          <button type="button" className="btn btn-primary" onClick={send} disabled={busy}>
            {busy ? <span className="spinner" /> : <IconPlay size={14} />} Send test request
          </button>
        </div>
        <ErrorCallout error={error} />
        {result && <ResultView result={result} showInput={false} />}
      </div>
    </Card>
  );
}

export function AgentEditor({
  initial,
  agentId,
}: {
  initial: Pick<Agent, "name" | "description" | "enabled" | "contract" | "params">;
  agentId?: string;
}) {
  const router = useRouter();
  const { toast } = useFeedback();
  const [form, setForm] = useState<FormState>(() => toForm(initial));
  const [tab, setTab] = useState<"form" | "json">("form");
  const [jsonText, setJsonText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [dirty, setDirty] = useState(false);

  const update = (patch: Partial<FormState>) => {
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
  };

  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  // JSON tab ↔ form: the form is the source of truth; the JSON tab edits a copy.
  const switchTab = (next: "form" | "json") => {
    if (next === tab) return;
    if (next === "json") {
      const built = fromForm(form);
      if ("error" in built) return setError(new ApiError(400, built.error));
      setJsonText(JSON.stringify(built, null, 2));
    } else {
      const parsed = parseJson(jsonText);
      if (!parsed.ok) return setError(new ApiError(400, `Fix the JSON before switching back: ${parsed.error}`));
      const v = parsed.value as { contract?: Contract; params?: Record<string, Json> };
      if (!v || typeof v !== "object" || !v.contract?.invoke) {
        return setError(new ApiError(400, 'JSON must look like {"contract": {"invoke": {...}}, "params": {...}}'));
      }
      setForm((f) => ({ ...toForm({ ...f, contract: v.contract!, params: v.params ?? {} }), name: f.name, description: f.description, enabled: f.enabled }));
    }
    setError(null);
    setTab(next);
  };

  const build = (): ReturnType<typeof fromForm> => {
    if (tab === "json") {
      const parsed = parseJson(jsonText);
      if (!parsed.ok) return { error: `JSON is invalid: ${parsed.error}` };
      const v = parsed.value as { contract: Contract; params?: Record<string, Json> };
      return { contract: v.contract, params: v.params ?? {} };
    }
    return fromForm(form);
  };

  const fieldErrors = useMemo(() => (error instanceof ApiError ? error.fieldErrors("contract.") : {}), [error]);
  const headerErrors = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(fieldErrors)) if (k.startsWith("invoke.headers.")) out[k.slice(15)] = v;
    return out;
  }, [fieldErrors]);

  const save = async () => {
    setError(null);
    const built = build();
    if ("error" in built) return setError(new ApiError(400, built.error));
    if (!form.name.trim()) return setError(new ApiError(400, "Give the agent a name."));
    setSaving(true);
    try {
      const body = { name: form.name.trim(), description: form.description, enabled: form.enabled, ...built };
      const saved = agentId ? await api.updateAgent(agentId, body) : await api.createAgent(body);
      setDirty(false);
      toast(agentId ? "Agent saved" : `Agent “${saved.name}” created`);
      if (!agentId) router.replace(`/agents/${saved.id}`);
    } catch (e) {
      setError(e);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } finally {
      setSaving(false);
    }
  };

  const hasSecretLiteral = form.headers.some(
    (h) => /authorization|api[-_]?key|token/i.test(h.key) && h.value.trim() && !/\$\{|\{\{/.test(h.value),
  );

  return (
    <div className="split-editor">
      <div className="stack">
        <ErrorCallout error={error} />

        <Card title="Basics">
          <div className="stack">
            <Field label="Name" htmlFor="agent-name">
              <input id="agent-name" className="input" value={form.name} onChange={(e) => update({ name: e.target.value })} />
            </Field>
            <Field label="Description" optional htmlFor="agent-desc">
              <input
                id="agent-desc"
                className="input"
                value={form.description}
                placeholder="What is this agent, and which environment does it point at?"
                onChange={(e) => update({ description: e.target.value })}
              />
            </Field>
            <label className="check">
              <input type="checkbox" checked={form.enabled} onChange={(e) => update({ enabled: e.target.checked })} />
              <span>
                Enabled <span className="faint small">— disabled agents can&apos;t be selected for new runs</span>
              </span>
            </label>
          </div>
        </Card>

        <Tabs
          value={tab}
          onChange={switchTab}
          tabs={[
            { value: "form", label: "Contract" },
            { value: "json", label: "Raw JSON" },
          ]}
        />

        {tab === "json" ? (
          <Card title="Contract and parameters as JSON" hint="Paste a contract from another environment or edit fields the form doesn't expose.">
            <JsonEditor value={jsonText} onChange={(v) => (setJsonText(v), setDirty(true))} rows={24} ariaLabel="Contract JSON" />
          </Card>
        ) : (
          <>
            <Card title="1 · Request" hint="How to call the agent for each case.">
              <div className="stack">
                <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                  <Field label="Method">
                    <select className="select" value={form.method} onChange={(e) => update({ method: e.target.value as HttpMethod })} style={{ width: 110 }}>
                      {["POST", "GET", "PUT", "PATCH", "DELETE"].map((m) => (
                        <option key={m}>{m}</option>
                      ))}
                    </select>
                  </Field>
                  <div className="grow">
                    <Field label="URL" error={fieldErrors["invoke.url"]} hint="Templates allowed, e.g. {{ agent.params.base_url }}/v1/chat">
                      <input
                        className="input mono"
                        value={form.url}
                        aria-invalid={fieldErrors["invoke.url"] ? "true" : undefined}
                        onChange={(e) => update({ url: e.target.value })}
                      />
                    </Field>
                  </div>
                </div>
                <Field label="Headers">
                  <KeyValueEditor
                    rows={form.headers}
                    onChange={(headers) => update({ headers })}
                    keyPlaceholder="Header"
                    valuePlaceholder="Value or ${ENV_VAR}"
                    addLabel="Add header"
                    suggestions={HEADER_SUGGESTIONS}
                    errors={headerErrors}
                  />
                </Field>
                {hasSecretLiteral && (
                  <Callout tone="warning" title="Keep credentials out of the contract">
                    Contracts are stored in the database. Reference an environment variable on the runner instead, e.g.{" "}
                    <code>{"Bearer ${AGENT_API_KEY}"}</code>.
                  </Callout>
                )}
                <Field label="Body">
                  <Segmented<BodyMode>
                    label="Body mode"
                    value={form.bodyMode}
                    onChange={(bodyMode) => update({ bodyMode })}
                    options={[
                      { value: "json", label: "JSON template" },
                      { value: "passthrough", label: "Send case input as-is" },
                      { value: "none", label: "No body" },
                    ]}
                  />
                </Field>
                {form.bodyMode === "json" && (
                  <JsonEditor value={form.bodyText} onChange={(bodyText) => update({ bodyText })} rows={7} ariaLabel="Body template" />
                )}
                {form.bodyMode === "passthrough" && (
                  <p className="muted small">Each case&apos;s <code>input</code> object is sent as the JSON body, unchanged.</p>
                )}
                <TemplateHelp />
                <Field label="Timeout (seconds)" error={fieldErrors["invoke.timeout_s"]}>
                  <input className="input" type="number" min={1} value={form.timeout} onChange={(e) => update({ timeout: e.target.value })} style={{ width: 120 }} />
                </Field>
              </div>
            </Card>

            <Card title="2 · Response" hint="Name → JSONPath. final_text is what expectations are checked against; numeric fields become metrics.">
              <KeyValueEditor
                rows={form.extract}
                onChange={(extract) => update({ extract })}
                keyPlaceholder="Field"
                valuePlaceholder="$.path.to.value"
                addLabel="Add field"
                suggestions={["final_text", "job_id", "status", "tokens"]}
                errors={Object.fromEntries(
                  Object.entries(fieldErrors)
                    .filter(([k]) => k.startsWith("extract"))
                    .map(([, v]) => [v.match(/extract\.([^:]+):/)?.[1] ?? "", v]),
                )}
              />
              {!form.extract.some((r) => r.key === "final_text") && (
                <p className="faint small" style={{ marginTop: 8 }}>
                  No <code>final_text</code> mapping: the raw response body is scored.
                </p>
              )}
            </Card>

            <Card
              title="3 · Async polling"
              hint="For agents that accept a job and finish later."
              actions={
                <label className="check">
                  <input type="checkbox" checked={form.pollEnabled} onChange={(e) => update({ pollEnabled: e.target.checked })} />
                  Poll for completion
                </label>
              }
            >
              {form.pollEnabled ? (
                <div className="stack">
                  <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                    <Field label="Method">
                      <select className="select" value={form.pollMethod} onChange={(e) => update({ pollMethod: e.target.value as "GET" | "POST" })} style={{ width: 90 }}>
                        <option>GET</option>
                        <option>POST</option>
                      </select>
                    </Field>
                    <div className="grow">
                      <Field label="Status URL" error={fieldErrors["poll.url_template"]} hint="Use values extracted above, e.g. …/jobs/{{ extracted.job_id }}">
                        <input className="input mono" value={form.pollUrl} onChange={(e) => update({ pollUrl: e.target.value })} />
                      </Field>
                    </div>
                  </div>
                  <div className="grid-2">
                    <Field label="Done when" error={fieldErrors["poll.done_when"]} hint="Stop polling when this holds">
                      <input className="input mono" value={form.doneWhen} onChange={(e) => update({ doneWhen: e.target.value })} />
                    </Field>
                    <Field label="Failed when" optional error={fieldErrors["poll.failed_when"]} hint="Terminal states that count as agent errors">
                      <input className="input mono" value={form.failedWhen} onChange={(e) => update({ failedWhen: e.target.value })} />
                    </Field>
                  </div>
                  <div className="grid-2">
                    <Field label="Interval (s)">
                      <input className="input" type="number" min={0.05} step={0.5} value={form.pollInterval} onChange={(e) => update({ pollInterval: e.target.value })} />
                    </Field>
                    <Field label="Give up after (s)">
                      <input className="input" type="number" min={1} value={form.pollTimeout} onChange={(e) => update({ pollTimeout: e.target.value })} />
                    </Field>
                  </div>
                  <Field label="Headers">
                    <KeyValueEditor rows={form.pollHeaders} onChange={(pollHeaders) => update({ pollHeaders })} keyPlaceholder="Header" addLabel="Add header" suggestions={HEADER_SUGGESTIONS} />
                  </Field>
                  <Field label="Extract from status response">
                    <KeyValueEditor rows={form.pollExtract} onChange={(pollExtract) => update({ pollExtract })} keyPlaceholder="Field" valuePlaceholder="$.path" addLabel="Add field" suggestions={["final_text", "status"]} />
                  </Field>
                </div>
              ) : (
                <p className="muted small">Off — the first response is the answer.</p>
              )}
            </Card>

            <Card title="Parameters" hint="Referenced as {{ agent.params.name }}. Duplicate an agent and change these to target another environment.">
              <KeyValueEditor rows={form.params} onChange={(params) => update({ params })} keyPlaceholder="Name" valuePlaceholder="Value (JSON or text)" addLabel="Add parameter" />
            </Card>
          </>
        )}

        <div className="row" style={{ position: "sticky", bottom: 0, padding: "12px 0", background: "var(--bg)", borderTop: "1px solid var(--border)" }}>
          <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
            {saving && <span className="spinner" />} {agentId ? "Save changes" : "Create agent"}
          </button>
          <button type="button" className="btn" onClick={() => router.push("/agents")}>
            Cancel
          </button>
          {dirty && <span className="faint small">Unsaved changes</span>}
        </div>
      </div>

      <div className="sticky-side">
        <TestPanel build={build} />
      </div>
    </div>
  );
}

export function AgentEditorLoader({ id }: { id: string }) {
  const [agent, setAgent] = useState<Agent | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api.agent(id).then(setAgent).catch(setError);
  }, [id]);
  if (error) return <ErrorCallout error={error} title={errorMessage(error)} />;
  if (!agent) return <Spinner label="Loading agent…" />;
  return <AgentEditor initial={agent} agentId={agent.id} />;
}
