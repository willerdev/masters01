"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Account = {
  id: string;
  display_name: string;
  broker: string;
  server: string;
  account_number: string;
  connection_method: string;
  status: string;
  currency: string;
  equity: string;
  balance: string;
  control_state: string;
  monitoring_enabled: boolean;
};

export default function AccountsPage() {
  const [rows, setRows] = useState<Account[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    apiJson<Account[]>("/api/v1/accounts").then(setRows).catch((err: Error) => setError(err.message));
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between">
        <PageTitle title="Accounts" detail="Each account keeps its own connection, rules, and audit trail." />
        <Link href="/accounts/new" className="primary inline-block px-3 py-2 rounded bg-accent text-[#1a1208] font-semibold text-sm">Add account</Link>
      </div>
      {error ? <p className="text-loss">{error}</p> : null}
      <table className="w-full text-sm border border-line bg-panel">
        <thead className="text-left text-muted">
          <tr>
            {["Name", "Number", "Method", "Status", "Control", "Equity", "Monitoring"].map((head) => (
              <th key={head} className="px-3 py-2 border-b border-line">{head}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-line">
              <td className="px-3 py-2"><Link href={`/accounts/${row.id}`} className="text-accent">{row.display_name}</Link></td>
              <td className="px-3 py-2 num">{row.account_number}</td>
              <td className="px-3 py-2">{row.connection_method}</td>
              <td className="px-3 py-2">{row.status}</td>
              <td className="px-3 py-2">{row.control_state}</td>
              <td className="px-3 py-2 num">{row.equity} {row.currency}</td>
              <td className="px-3 py-2">{row.monitoring_enabled ? "On" : "Off"}</td>
            </tr>
          ))}
          {rows.length === 0 ? <tr><td className="px-3 py-6 text-muted" colSpan={7}>No accounts yet.</td></tr> : null}
        </tbody>
      </table>
    </div>
  );
}
