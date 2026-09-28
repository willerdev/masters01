"use client";

import { useEffect, useState } from "react";
import { EquityChart, ExposureChart } from "@/components/Charts";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Portfolio = {
  total_capital: string;
  total_equity: string;
  total_exposure: string;
  total_open_risk: string;
  combined_drawdown: string;
  account_drawdown: { name: string; balance: string; equity: string; drawdown: string; open_risk: string }[];
  symbol_exposure: { symbol: string; notional: string }[];
  correlation_exposure: { left: string; right: string; overlap: string; combined_notional: string }[];
};

export default function AnalyticsPage() {
  const [book, setBook] = useState<Portfolio | null>(null);
  const [charts, setCharts] = useState<{ equity: { t: string; equity: string }[]; exposure: { symbol: string; notional: string }[] } | null>(null);

  useEffect(() => {
    apiJson<Portfolio>("/api/v1/portfolio").then(setBook);
    apiJson<typeof charts>("/api/v1/dashboard/charts").then(setCharts);
  }, []);

  return (
    <div>
      <PageTitle title="Analytics" detail="Portfolio capital, exposure, and account-level drawdown." />
      {book ? (
        <section className="grid md:grid-cols-5 gap-3 mb-6">
          {[
            ["Total capital", book.total_capital],
            ["Total equity", book.total_equity],
            ["Total exposure", book.total_exposure],
            ["Open risk", book.total_open_risk],
            ["Combined drawdown %", book.combined_drawdown],
          ].map(([label, value]) => (
            <article key={label} className="bg-panel border border-line rounded px-3 py-2">
              <div className="text-[11px] uppercase text-muted">{label}</div>
              <div className="num">{value}</div>
            </article>
          ))}
        </section>
      ) : null}
      <table className="w-full text-sm bg-panel border border-line mb-6">
        <thead className="text-left text-muted"><tr><th className="px-3 py-2">Account</th><th>Balance</th><th>Equity</th><th>Drawdown %</th><th>Open risk</th></tr></thead>
        <tbody>
          {(book?.account_drawdown || []).map((row) => (
            <tr key={row.name} className="border-t border-line">
              <td className="px-3 py-2">{row.name}</td>
              <td className="px-3 py-2 num">{row.balance}</td>
              <td className="px-3 py-2 num">{row.equity}</td>
              <td className="px-3 py-2 num">{row.drawdown}</td>
              <td className="px-3 py-2 num">{row.open_risk}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(book?.correlation_exposure || []).length ? (
        <p className="text-sm text-muted mb-4">Shared-currency exposure: {book?.correlation_exposure.map((row) => `${row.left}/${row.right} overlap ${row.overlap}`).join("; ")}</p>
      ) : null}
      {charts ? (
        <div className="grid xl:grid-cols-2 gap-4">
          <EquityChart data={charts.equity} />
          <ExposureChart data={charts.exposure} />
        </div>
      ) : null}
    </div>
  );
}
