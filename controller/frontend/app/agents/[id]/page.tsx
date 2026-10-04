"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AgentEditorLoader } from "@/components/AgentEditor";
import { IconPlay } from "@/components/icons";
import { PageHeader } from "@/components/ui";

export default function EditAgentPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <PageHeader
        title="Edit agent"
        crumbs={[{ href: "/agents", label: "Agents" }]}
        actions={
          <Link href={`/runs/new?agent=${id}`} className="btn">
            <IconPlay size={14} /> Run evaluation
          </Link>
        }
      />
      <AgentEditorLoader id={id} />
    </>
  );
}
