"use client";

import { useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Row = { id: string; action: string; actor_type: string; entity_type: string; entity_id: string; created_at: string; after: Record<string, unknown> | null };

export default function AuditPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    apiJson<Row[]>("/api/v1/audit-logs").then(setRows).catch((err: Error) => setError(err.message));
  }, []);

  return (
    <div>
      <PageTitle title="Audit log" detail="Append-only. The desk has no edit or delete action for these rows." />
      {error ? <p className="text-loss">{error}</p> : null}
      <table className="w-full text-sm bg-panel border border-line">
        <thead className="text-left text-muted">
          <tr>{["When", "Action", "Actor", "Entity"].map((head) => <th key={head} className="px-3 py-2">{head}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-line">
              <td className="px-3 py-2 num">{row.created_at.replace("T", " ").slice(0, 19)}</td>
              <td className="px-3 py-2">{row.action}</td>
              <td className="px-3 py-2">{row.actor_type}</td>
              <td className="px-3 py-2">{row.entity_type} {row.entity_id.slice(0, 8)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
