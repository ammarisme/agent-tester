import type { Run } from "@/lib/api";
import { pct, shortId } from "@/lib/format";
import { seriesVar } from "@/lib/outcomes";

export function runTitle(r: Pick<Run, "name" | "id">) {
  return r.name || `Run ${shortId(r.id)}`;
}

/** Headline rate per agent: pass rate when scored, otherwise success rate. */
export function headline(s: { pass_rate: number | null; success_rate: number | null }) {
  return s.pass_rate ?? s.success_rate;
}

export function AgentRates({ run }: { run: Run }) {
  return (
    <div className="stack-sm" style={{ gap: 2 }}>
      {run.agents.map((a, i) => {
        const s = run.summary?.[a.id];
        return (
          <span key={a.id} className="row small" style={{ gap: 6, flexWrap: "nowrap" }}>
            <span className="swatch" style={{ background: seriesVar(i), width: 8, height: 8 }} />
            <span className="truncate" style={{ maxWidth: 180 }}>{a.name}</span>
            {s && <strong className="num">{pct(headline(s), 0)}</strong>}
          </span>
        );
      })}
    </div>
  );
}
