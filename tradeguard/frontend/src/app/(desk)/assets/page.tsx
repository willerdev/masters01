"use client";

import { PageTitle } from "@/components/Shell";
import { AssetPanel } from "@/components/AssetPanel";

export default function AssetsPage() {
  return (
    <div className="max-w-4xl">
      <PageTitle title="Assets" detail="Crypto held with NOWPayments for this login." />
      <AssetPanel />
    </div>
  );
}
