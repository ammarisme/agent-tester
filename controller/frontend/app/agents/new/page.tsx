"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { api, type Preset } from "@/lib/api";
import { useResource } from "@/lib/hooks";
import { AgentEditor, BLANK_CONTRACT } from "@/components/AgentEditor";
import { ErrorCallout, PageHeader, Skeleton } from "@/components/ui";

function PresetPicker({ presets }: { presets: Preset[] }) {
  const router = useRouter();
  const pick = (id: string) => router.push(`/agents/new?preset=${encodeURIComponent(id)}`);
  const groups: [string, string, Preset[]][] = [
    ["Templates", "Point one at your own agent — replace the URL and response paths.", presets.filter((p) => p.category !== "demo")],
    ["Bundled mock agents", "Work immediately with no credentials. Good for learning the workflow.", presets.filter((p) => p.category === "demo")],
  ];
  return (
    <div className="stack" style={{ gap: 28 }}>
      {groups.map(([title, hint, items]) =>
        items.length ? (
          <section key={title} className="stack-sm">
            <h2>{title}</h2>
            <p className="muted small">{hint}</p>
            <div className="grid-auto" style={{ marginTop: 4 }}>
              {items.map((p) => (
                <button key={p.id} type="button" className="choice" onClick={() => pick(p.id)}>
                  <strong>{p.name}</strong>
                  <span className="desc">{p.description}</span>
                  <span className="mono faint small truncate" style={{ maxWidth: "100%" }}>
                    {p.contract.invoke.method} {p.contract.invoke.url}
                  </span>
                </button>
              ))}
            </div>
          </section>
        ) : null,
      )}
      <section className="stack-sm">
        <h2>From scratch</h2>
        <div className="grid-auto">
          <button type="button" className="choice" onClick={() => pick("blank")}>
            <strong>Blank contract</strong>
            <span className="desc">A minimal POST request. You fill in everything.</span>
          </button>
        </div>
      </section>
    </div>
  );
}

function NewAgent() {
  const params = useSearchParams();
  const presetId = params.get("preset");
  const { data: presets, error } = useResource(api.presets, []);

  if (error) return <ErrorCallout error={error} />;
  if (!presets) return <Skeleton rows={4} />;
  if (!presetId) return <PresetPicker presets={presets} />;

  const preset = presets.find((p) => p.id === presetId);
  const initial = preset
    ? { name: preset.name, description: preset.description ?? "", enabled: true, contract: preset.contract, params: preset.params ?? {} }
    : { name: "New agent", description: "", enabled: true, contract: BLANK_CONTRACT, params: {} };
  return <AgentEditor key={presetId} initial={initial} />;
}

export default function NewAgentPage() {
  return (
    <>
      <PageHeader
        title="New agent"
        crumbs={[{ href: "/agents", label: "Agents" }]}
        subtitle="Describe how to call your agent. Use the test panel to check the request before saving."
      />
      <Suspense fallback={<Skeleton rows={4} />}>
        <NewAgent />
      </Suspense>
    </>
  );
}
