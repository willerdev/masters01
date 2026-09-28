"use client";

import { useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Row = Record<string, string | number | null>;

const COLUMNS: [string, string][] = [
  ["ticket", "Ticket"],
  ["symbol", "Symbol"],
  ["direction", "Direction"],
  ["lot", "Lot"],
  ["entry", "Entry"],
  ["current_price", "Current"],
  ["stop_loss", "Stop loss"],
  ["take_profit", "Take profit"],
  ["floating_pl", "Floating P/L"],
  ["risk_amount", "Risk amount"],
  ["risk_percent", "Risk %"],
  ["duration", "Duration"],
  ["strategy", "Source"],
  ["magic_number", "Magic"],
];

export default function PositionsPage() {
  const [rows, setRows] = useState<Row[]>([]);

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const load = async () => {
      try {
        const body = await apiJson<{ trades: Row[] }>("/api/v1/trades");
        if (!stopped) setRows(body.trades || []);
      } catch {
        /* keep the last book on a transient miss */
      } finally {
        if (!stopped) timer = window.setTimeout(load, 1000);
      }
    };
    load();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, []);

  return (
    <div>
      <PageTitle title="Positions" detail="Open positions across visible accounts. Prices refresh every second from the latest terminal read." />
      <div className="overflow-x-auto border border-line bg-panel">
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr>{COLUMNS.map(([, label]) => <th key={label} className="px-2 py-2 whitespace-nowrap">{label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.account_id}-${row.ticket}`} className="border-t border-line">
                {COLUMNS.map(([key]) => <td key={key} className="px-2 py-2 num whitespace-nowrap">{row[key] ?? "—"}</td>)}
              </tr>
            ))}
            {rows.length === 0 ? <tr><td className="px-3 py-6 text-muted" colSpan={COLUMNS.length}>No open positions.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
