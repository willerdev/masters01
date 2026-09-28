"use client";

import { useParams } from "next/navigation";
import { PageTitle } from "@/components/Shell";
import { RiskRulesForm } from "@/components/RiskRulesForm";

export default function RulesPage() {
  const params = useParams<{ id: string }>();

  return (
    <div>
      <PageTitle title="Account risk rules" detail="Turn a rule off to stop the engine from using it. The limit stays saved for when you turn it back on." />
      <RiskRulesForm accountId={params.id} />
    </div>
  );
}
