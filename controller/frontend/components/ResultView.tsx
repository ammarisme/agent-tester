"use client";

import type { TestResult, TrajectoryStep } from "@/lib/api";
import { ms, pretty } from "@/lib/format";
import { outcomeMeta } from "@/lib/outcomes";
import { IconChevron } from "./icons";
import { Callout, CodeBlock, OutcomeBadge, Stat } from "./ui";

function tryPretty(body: string | undefined): string {
  if (!body) return "";
  try {
    return JSON.stringify(JSON.parse(body), null, 2);
  } catch {
    return body;
  }
}

function Step({ step, defaultOpen }: { step: TrajectoryStep; defaultOpen: boolean }) {
  const ok = step.status_code != null ? step.status_code < 400 : undefined;
  const hasHeaders = step.request_headers && Object.keys(step.request_headers).length > 0;
  return (
    <details className="step" open={defaultOpen}>
      <summary>
        <IconChevron className="chev" size={14} />
        <span className="tag">{step.phase === "poll" ? `poll #${step.attempt ?? ""}` : "invoke"}</span>
        <span className="method">{step.method}</span>
        <span className="mono truncate grow" title={step.url}>
          {step.url ?? "—"}
        </span>
        {step.status_code != null && (
          <span className="status-code" data-ok={String(ok)}>
            {step.status_code}
          </span>
        )}
        {step.error && !step.status_code && <span className="badge" data-tone="critical"><span className="dot" />error</span>}
        {step.latency_ms != null && <span className="faint small num nowrap">{ms(step.latency_ms)}</span>}
      </summary>
      <div className="step-body">
        {step.error && <Callout tone="danger">{step.error}</Callout>}
        {hasHeaders && (
          <div>
            <div className="faint small">Request headers <span className="faint">(secrets masked)</span></div>
            <CodeBlock value={step.request_headers} maxHeight={160} />
          </div>
        )}
        {step.request_body !== undefined && step.request_body !== null && (
          <div>
            <div className="faint small">Request body</div>
            <CodeBlock value={step.request_body} maxHeight={220} />
          </div>
        )}
        {step.response_body !== undefined && (
          <div>
            <div className="faint small">
              Response body {step.content_type && <span className="faint">· {step.content_type}</span>}
            </div>
            <CodeBlock value={tryPretty(step.response_body)} maxHeight={320} />
          </div>
        )}
      </div>
    </details>
  );
}

export function Trajectory({ steps, omitted }: { steps: TrajectoryStep[]; omitted?: number }) {
  if (!steps.length) return <p className="faint">No HTTP steps were recorded.</p>;
  return (
    <div className="timeline">
      {steps.map((s, i) => (
        <Step key={i} step={s} defaultOpen={steps.length <= 2 || i === steps.length - 1} />
      ))}
      {omitted ? <p className="faint small">{omitted} further poll steps were not recorded.</p> : null}
    </div>
  );
}

/** Everything about one evaluated case, used by the test panel and the run drawer. */
export function ResultView({ result, showInput = true }: { result: TestResult; showInput?: boolean }) {
  const meta = outcomeMeta(result.outcome_class);
  const steps = result.trajectory?.steps ?? [];
  const warnings = result.trajectory?.warnings ?? [];
  const extraMetrics = Object.entries(result.metrics ?? {}).filter(([k]) => k !== "latency_ms");
  return (
    <div className="stack">
      <div className="row-between">
        <div className="row">
          <OutcomeBadge outcome={result.outcome_class} />
          {result.passed === true && <span className="badge" data-tone="good"><span className="dot" />Passed</span>}
          {result.passed === false && <span className="badge" data-tone="warning"><span className="dot" />Did not pass</span>}
        </div>
      </div>

      <div className="stats">
        <Stat label="Latency" value={ms(result.latency_ms)} />
        <Stat label="HTTP status" value={result.status_code ?? "—"} />
        <Stat label="Steps" value={steps.length} />
        {extraMetrics.slice(0, 3).map(([k, v]) => (
          <Stat key={k} label={k} value={Number.isInteger(v) ? v : v.toFixed(2)} />
        ))}
      </div>

      {result.outcome_class !== "success" && result.outcome_class !== "failed_assert" && (
        <Callout tone="danger" title={result.error ?? meta.label}>
          {meta.action}
        </Callout>
      )}
      {result.failures?.length > 0 && result.outcome_class === "failed_assert" && (
        <Callout tone="warning" title="Expectations that failed">
          <ul>
            {result.failures.map((f, i) => (
              <li key={i} className="mono">{f}</li>
            ))}
          </ul>
        </Callout>
      )}
      {warnings.length > 0 && (
        <Callout tone="neutral" title="Extraction warnings">
          <ul>
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Callout>
      )}

      <div className="stack-sm">
        <h3>Final text <span className="faint small" style={{ fontWeight: 400 }}>— what expectations are checked against</span></h3>
        <CodeBlock value={result.final_text ?? ""} maxHeight={240} />
      </div>

      {showInput && (
        <div className="grid-2">
          <div className="stack-sm">
            <h3>Input</h3>
            <CodeBlock value={pretty(result.input)} maxHeight={220} />
          </div>
          <div className="stack-sm">
            <h3>Expected</h3>
            {result.expected ? <CodeBlock value={result.expected} maxHeight={220} /> : <p className="faint small">No expectations — scored on outcome only.</p>}
          </div>
        </div>
      )}

      {Object.keys(result.extracted ?? {}).length > 0 && (
        <div className="stack-sm">
          <h3>Extracted fields</h3>
          <CodeBlock value={result.extracted} maxHeight={220} />
        </div>
      )}

      <div className="stack-sm">
        <h3>Trajectory</h3>
        <Trajectory steps={steps} omitted={result.trajectory?.poll_steps_omitted} />
      </div>
    </div>
  );
}
