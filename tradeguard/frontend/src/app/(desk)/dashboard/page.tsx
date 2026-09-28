"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DailyPnlChart, DrawdownChart, EquityChart, ExposureChart, FrequencyChart, UtilizationChart, WinLossChart } from "@/components/Charts";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Summary = Record<string, string | number>;
type Charts = {
  equity: { t: string; equity: string }[];
  drawdown: { t: string; drawdown: string }[];
  daily_pnl: { date: string; pnl: string }[];
  trade_frequency: { bucket: string; count: number }[];
  risk_utilization: { account: string; percent: string }[];
  exposure: { symbol: string; notional: string }[];
  win_loss: { wins: number; losses: number };
};

const TILES: [string, string][] = [
  ["total_accounts", "Total accounts"],
  ["connected_accounts", "Connected"],
  ["total_balance", "Total balance"],
  ["total_equity", "Total equity"],
  ["total_open_risk", "Open risk"],
  ["today_pl", "Today P/L"],
  ["today_loss", "Today loss"],
  ["current_drawdown", "Current drawdown %"],
  ["max_drawdown", "Max drawdown %"],
  ["open_positions", "Open positions"],
  ["trades_today", "Trades today"],
  ["risk_violations", "Risk violations"],
  ["account_health", "Account health"],
];

export default function DashboardPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [charts, setCharts] = useState<Charts | null>(null);
  const [error, setError] = useState("");
  const [paymentNeeded, setPaymentNeeded] = useState(false);

  useEffect(() => {
    apiJson<{ configured: boolean }>("/api/v1/payments/provider")
      .then((body) => setPaymentNeeded(!body.configured))
      .catch(() => setPaymentNeeded(false));
    Promise.all([apiJson<Summary>("/api/v1/dashboard/summary"), apiJson<Charts>("/api/v1/dashboard/charts")])
      .then(([sum, chart]) => {
        setSummary(sum);
        setCharts(chart);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <div>
      <PageTitle title="Dashboard" detail="Firm-wide risk picture across monitored MT5 accounts." />
      {error ? <p className="text-loss">{error}</p> : null}
      {paymentNeeded ? (
        <p className="mb-4 text-sm border border-line bg-panel rounded-lg px-3 py-3">
          Connect a crypto payment provider. <Link className="text-accent" href="/payments">Choose NOWPayments or Cryptomus</Link>.
        </p>
      ) : null}
      <section className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3 mb-6">
        {TILES.map(([key, label]) => (
          <article key={key} className="bg-panel border border-line rounded-lg px-3 py-3">
            <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
            <div className={`num text-lg mt-1 ${tone(key, summary?.[key])}`}>{summary ? String(summary[key]) : "—"}</div>
          </article>
        ))}
      </section>
      {charts ? (
        <section className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <EquityChart data={charts.equity} />
          <DrawdownChart data={charts.drawdown} />
          <DailyPnlChart data={charts.daily_pnl} />
          <FrequencyChart data={charts.trade_frequency} />
          <UtilizationChart data={charts.risk_utilization} />
          <ExposureChart data={charts.exposure} />
          <WinLossChart wins={charts.win_loss.wins} losses={charts.win_loss.losses} />
        </section>
      ) : null}
    </div>
  );
}

function tone(key: string, value: string | number | undefined) {
  if (value === undefined) return "";
  if (key === "today_pl") return Number(value) < 0 ? "text-loss" : "text-profit";
  if (key === "account_health") {
    if (value === "CRITICAL" || value === "HIGH_RISK") return "text-loss";
    if (value === "WARNING") return "text-warn";
    if (value === "HEALTHY") return "text-profit";
  }
  return "";
}
