"use client";

import { useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { RiskRulesForm } from "@/components/RiskRulesForm";
import { apiJson } from "@/lib/api";

type Account = { id: string; display_name: string; account_number: string };

export default function RiskRulesPage() {
  const [rows, setRows] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");

  useEffect(() => {
    apiJson<Account[]>("/api/v1/accounts").then((accounts) => {
      setRows(accounts);
      setAccountId((current) => current || accounts[0]?.id || "");
    });
  }, []);

  return (
    <div>
      <PageTitle
        title="Risk rules"
        detail="Every limit starts off. Turn on only the ones you want. Account pause and emergency stop still apply."
      />
      {rows.length > 1 ? (
        <label className="text-sm flex flex-col gap-1 max-w-sm mb-4">
          Account
          <select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            {rows.map((row) => (
              <option key={row.id} value={row.id}>{row.display_name} · {row.account_number}</option>
            ))}
          </select>
        </label>
      ) : null}
      {accountId ? <RiskRulesForm key={accountId} accountId={accountId} /> : <p className="text-sm text-muted">Connect an account to edit its risk rules.</p>}
    </div>
  );
}
