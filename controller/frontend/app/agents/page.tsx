"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, errorMessage, type Agent } from "@/lib/api";
import { relTime } from "@/lib/format";
import { useNow, useResource } from "@/lib/hooks";
import { IconAgent, IconCopy, IconEdit, IconPlay, IconPlus, IconTrash } from "@/components/icons";
import { Menu, useFeedback } from "@/components/overlays";
import { Card, EmptyState, ErrorCallout, PageHeader, Skeleton } from "@/components/ui";

function endpoint(a: Agent) {
  const { method, url } = a.contract.invoke ?? {};
  return `${method ?? ""} ${url ?? ""}`.trim();
}

export default function AgentsPage() {
  const router = useRouter();
  const now = useNow();
  const { toast, confirm } = useFeedback();
  const { data: agents, error, loading, reload, mutate } = useResource(api.agents, []);

  const toggle = async (a: Agent) => {
    mutate((list) => list?.map((x) => (x.id === a.id ? { ...x, enabled: !a.enabled } : x)));
    try {
      await api.updateAgent(a.id, { enabled: !a.enabled });
    } catch (e) {
      toast(errorMessage(e), "danger");
      reload();
    }
  };

  const remove = async (a: Agent) => {
    const ok = await confirm({
      title: `Delete “${a.name}”?`,
      body: "Past runs keep their results and the agent's name. This can't be undone.",
      confirmLabel: "Delete agent",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.deleteAgent(a.id);
      toast("Agent deleted");
      reload();
    } catch (e) {
      toast(errorMessage(e), "danger");
    }
  };

  const duplicate = async (a: Agent) => {
    try {
      const copy = await api.duplicateAgent(a.id);
      router.push(`/agents/${copy.id}`);
    } catch (e) {
      toast(errorMessage(e), "danger");
    }
  };

  return (
    <>
      <PageHeader
        title="Agents"
        subtitle="An agent is an HTTP contract: how to call your endpoint, what to send, and which part of the response to score."
        actions={
          <Link href="/agents/new" className="btn btn-primary">
            <IconPlus size={14} /> New agent
          </Link>
        }
      />
      <ErrorCallout error={error} />
      <Card flush>
        {loading && !agents ? (
          <div className="card-body">
            <Skeleton rows={4} />
          </div>
        ) : agents && agents.length === 0 ? (
          <EmptyState
            icon={<IconAgent size={22} />}
            title="No agents yet"
            actions={
              <Link href="/agents/new" className="btn btn-primary">
                <IconPlus size={14} /> New agent
              </Link>
            }
          >
            Start from a template (sync, async or OpenAI-compatible) or the bundled mock agents, then send a test request before saving.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Endpoint</th>
                  <th>Mode</th>
                  <th>Enabled</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {agents?.map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => router.push(`/agents/${a.id}`)}>
                    <td style={{ maxWidth: 280 }}>
                      <Link href={`/agents/${a.id}`} onClick={(e) => e.stopPropagation()} style={{ fontWeight: 500, color: "var(--text)" }}>
                        {a.name}
                      </Link>
                      {a.description && <div className="faint small truncate">{a.description}</div>}
                    </td>
                    <td className="mono small truncate" style={{ maxWidth: 360 }} title={endpoint(a)}>
                      {endpoint(a)}
                    </td>
                    <td>
                      <span className="tag">{a.contract.poll ? "async · poll" : "sync"}</span>
                    </td>
                    <td onClick={(e) => e.stopPropagation()}>
                      <label className="check" title={a.enabled ? "Disable" : "Enable"}>
                        <input type="checkbox" checked={a.enabled} onChange={() => toggle(a)} aria-label={`Enable ${a.name}`} />
                      </label>
                    </td>
                    <td className="faint small nowrap">{relTime(a.updated_at, now)}</td>
                    <td className="right" onClick={(e) => e.stopPropagation()}>
                      <Menu
                        items={[
                          { label: "Edit", icon: <IconEdit size={14} />, onSelect: () => router.push(`/agents/${a.id}`) },
                          { label: "Run evaluation", icon: <IconPlay size={14} />, onSelect: () => router.push(`/runs/new?agent=${a.id}`), disabled: !a.enabled },
                          { label: "Duplicate", icon: <IconCopy size={14} />, onSelect: () => duplicate(a) },
                          "separator",
                          { label: "Delete", icon: <IconTrash size={14} />, onSelect: () => remove(a), danger: true },
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
    </>
  );
}
