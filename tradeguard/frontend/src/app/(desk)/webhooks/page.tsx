"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Account = { id: string; display_name: string; account_number: string; connection_method: string; status: string };

export default function WebhooksPage() {
  const [rows, setRows] = useState<Account[]>([]);

  useEffect(() => {
    apiJson<Account[]>("/api/v1/accounts").then(setRows);
  }, []);

  return (
    <div>
      <PageTitle title="Webhooks" detail="Each webhook account has a private URL, API key, and signing secret. Secrets are shown once at creation and are not listed here." />
      <table className="w-full text-sm bg-panel border border-line">
        <thead className="text-left text-muted"><tr><th className="px-3 py-2">Account</th><th>Number</th><th>Method</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-line">
              <td className="px-3 py-2"><Link className="text-accent" href={`/accounts/${row.id}`}>{row.display_name}</Link></td>
              <td className="px-3 py-2 num">{row.account_number}</td>
              <td className="px-3 py-2">{row.connection_method}</td>
              <td className="px-3 py-2">{row.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
