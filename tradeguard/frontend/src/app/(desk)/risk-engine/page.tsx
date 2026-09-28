"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Decision = { id: string; decision: string; created_at: string; hits: { code: string; message?: string }[] };
type Sim = Record<string, string | number | null | object>;

export default function RiskEnginePage() {
  const [rows, setRows] = useState<Decision[]>([]);
  const [result, setResult] = useState<Sim | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiJson<Decision[]>("/api/v1/risk-decisions").then(setRows).catch((err: Error) => setError(err.message));
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const take = String(form.get("take_profit") || "");
    try {
      const body = await apiJson<Sim>("/api/v1/simulate", {
        method: "POST",
        body: JSON.stringify({
          balance: form.get("balance"),
          risk_percent: form.get("risk_percent"),
          symbol: form.get("symbol"),
          entry_price: form.get("entry_price"),
          stop_loss: form.get("stop_loss"),
          lot_size: form.get("lot_size"),
          take_profit: take || null,
          loss_count: 5,
          daily_loss_percent: "3",
          risk_to_percent: "2",
        }),
      });
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Simulation failed");
    }
  }

  const streak = result?.loss_streak as { equity_after?: string; capital_lost?: string } | undefined;
  const daily = result?.daily_loss as { equity_after?: string; loss_amount?: string } | undefined;
  const change = result?.risk_change as { loss_budget_from?: string; loss_budget_to?: string } | undefined;

  return (
    <div>
      <PageTitle title="Risk engine" detail="Deterministic sizing and the stored decision log. AI is not on this path." />
      {error ? <p className="text-loss mb-3">{error}</p> : null}
      <form className="grid md:grid-cols-3 gap-3 max-w-4xl mb-6" onSubmit={onSubmit}>
        <input name="balance" type="number" step="0.01" defaultValue="10000" placeholder="Balance" />
        <input name="risk_percent" type="number" step="0.01" defaultValue="1" placeholder="Risk %" />
        <input name="symbol" defaultValue="EURUSD" />
        <input name="entry_price" type="number" step="0.00001" defaultValue="1.10000" />
        <input name="stop_loss" type="number" step="0.00001" defaultValue="1.09800" />
        <input name="take_profit" type="number" step="0.00001" defaultValue="1.10400" placeholder="Take profit" />
        <input name="lot_size" type="number" step="0.01" defaultValue="0.10" />
        <button className="primary" type="submit">Calculate</button>
      </form>
      {result ? (
        <section className="grid md:grid-cols-3 gap-3 mb-8">
          <Metric label="Potential loss" value={String(result.potential_loss)} />
          <Metric label="Risk %" value={String(result.risk_percentage)} />
          <Metric label="Suggested size" value={String(result.suggested_volume ?? "—")} />
          <Metric label="Margin" value={String(result.margin_requirement)} />
          <Metric label="Exposure" value={String(result.exposure)} />
          <Metric label="Risk / reward" value={String(result.risk_reward ?? "—")} />
          <Metric label="After 5 losses at this risk" value={streak?.equity_after || "—"} />
          <Metric label="If daily loss hits 3%" value={`${daily?.loss_amount} → ${daily?.equity_after}`} />
          <Metric label="Loss budget 1% vs 2%" value={`${change?.loss_budget_from} → ${change?.loss_budget_to}`} />
        </section>
      ) : null}
      <h2 className="mb-2">Recent decisions</h2>
      <table className="w-full text-sm bg-panel border border-line">
        <thead className="text-left text-muted"><tr><th className="px-3 py-2">When</th><th>Decision</th><th>Checks</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-line">
              <td className="px-3 py-2 num">{row.created_at.replace("T", " ").slice(0, 19)}</td>
              <td className="px-3 py-2">{row.decision}</td>
              <td className="px-3 py-2">{(row.hits || []).map((hit) => hit.code).join(", ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <article className="bg-panel border border-line rounded px-3 py-2">
      <div className="text-[11px] uppercase text-muted">{label}</div>
      <div className="num">{value}</div>
    </article>
  );
}
