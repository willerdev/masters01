"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useEffect, useState, type ReactElement, type ReactNode } from "react";

const FALLBACK = {
  accent: "#d7a15a",
  profit: "#3dbe86",
  loss: "#ff6b7d",
  warn: "#e0b15a",
  line: "#2c343d",
  muted: "#9aa3ad",
};

function useInk() {
  const [ink, setInk] = useState(FALLBACK);
  useEffect(() => {
    const style = getComputedStyle(document.documentElement);
    const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
    setInk({
      accent: read("--accent", FALLBACK.accent),
      profit: read("--profit", FALLBACK.profit),
      loss: read("--loss", FALLBACK.loss),
      warn: read("--warn", FALLBACK.warn),
      line: read("--line", FALLBACK.line),
      muted: read("--muted", FALLBACK.muted),
    });
  }, []);
  return ink;
}

function ChartCanvas({ children }: { children: ReactElement }) {
  return (
    <div className="h-[220px] w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 520, height: 220 }}>
        {children}
      </ResponsiveContainer>
    </div>
  );
}

export function EquityChart({ data }: { data: { t: string; equity: string }[] }) {
  const ink = useInk();
  const rows = data.map((row) => ({ t: row.t.slice(5, 16), equity: Number(row.equity) }));
  return (
    <ChartFrame title="Equity curve" empty={rows.length === 0}>
      <ChartCanvas>
        <LineChart data={rows}>
          <CartesianGrid stroke={ink.line} vertical={false} />
          <XAxis dataKey="t" tick={{ fill: ink.muted, fontSize: 11 }} />
          <YAxis tick={{ fill: ink.muted, fontSize: 11 }} width={72} domain={["auto", "auto"]} />
          <Tooltip />
          <Line type="monotone" dataKey="equity" stroke={ink.accent} dot={rows.length < 8} strokeWidth={2} name="Equity" />
        </LineChart>
      </ChartCanvas>
    </ChartFrame>
  );
}

export function DrawdownChart({ data }: { data: { t: string; drawdown: string }[] }) {
  const ink = useInk();
  const rows = data.map((row) => ({ t: row.t.slice(5, 16), drawdown: Number(row.drawdown) }));
  return (
    <ChartFrame title="Drawdown %" empty={rows.length === 0}>
      <ChartCanvas>
        <LineChart data={rows}>
          <CartesianGrid stroke={ink.line} vertical={false} />
          <XAxis dataKey="t" tick={{ fill: ink.muted, fontSize: 11 }} />
          <YAxis tick={{ fill: ink.muted, fontSize: 11 }} width={48} />
          <Tooltip />
          <Line type="monotone" dataKey="drawdown" stroke={ink.loss} dot={rows.length < 8} strokeWidth={2} name="Drawdown %" />
        </LineChart>
      </ChartCanvas>
    </ChartFrame>
  );
}

export function DailyPnlChart({ data }: { data: { date: string; pnl: string }[] }) {
  const ink = useInk();
  const rows = data.map((row) => ({ date: row.date.slice(5), pnl: Number(row.pnl) }));
  return (
    <ChartFrame title="Daily P/L" empty={rows.length === 0}>
      <ChartCanvas>
        <BarChart data={rows}>
          <CartesianGrid stroke={ink.line} vertical={false} />
          <XAxis dataKey="date" tick={{ fill: ink.muted, fontSize: 11 }} />
          <YAxis tick={{ fill: ink.muted, fontSize: 11 }} width={56} />
          <Tooltip />
          <Bar dataKey="pnl" name="P/L">
            {rows.map((row) => (
              <Cell key={row.date} fill={row.pnl >= 0 ? ink.profit : ink.loss} />
            ))}
          </Bar>
        </BarChart>
      </ChartCanvas>
    </ChartFrame>
  );
}

export function FrequencyChart({ data }: { data: { bucket: string; count: number }[] }) {
  const ink = useInk();
  return (
    <ChartFrame title="Trade frequency" empty={data.length === 0}>
      <ChartCanvas>
        <BarChart data={data}>
          <CartesianGrid stroke={ink.line} vertical={false} />
          <XAxis dataKey="bucket" tick={{ fill: ink.muted, fontSize: 11 }} hide={data.length > 12} />
          <YAxis tick={{ fill: ink.muted, fontSize: 11 }} width={32} allowDecimals={false} />
          <Tooltip />
          <Bar dataKey="count" fill={ink.accent} name="Trades" />
        </BarChart>
      </ChartCanvas>
    </ChartFrame>
  );
}

export function UtilizationChart({ data }: { data: { account: string; percent: string }[] }) {
  const ink = useInk();
  const rows = data.map((row) => ({ account: row.account, percent: Number(row.percent) }));
  return (
    <ChartFrame title="Risk utilization %" empty={rows.length === 0}>
      <ChartCanvas>
        <BarChart data={rows}>
          <CartesianGrid stroke={ink.line} vertical={false} />
          <XAxis dataKey="account" tick={{ fill: ink.muted, fontSize: 11 }} />
          <YAxis tick={{ fill: ink.muted, fontSize: 11 }} width={40} />
          <Tooltip />
          <Bar dataKey="percent" fill={ink.warn} name="Open risk %" />
        </BarChart>
      </ChartCanvas>
    </ChartFrame>
  );
}

export function ExposureChart({ data }: { data: { symbol: string; notional: string }[] }) {
  const ink = useInk();
  const rows = data.map((row) => ({ symbol: row.symbol, notional: Number(row.notional) }));
  return (
    <ChartFrame title="Exposure" empty={rows.length === 0}>
      <ChartCanvas>
        <BarChart data={rows} layout="vertical">
          <CartesianGrid stroke={ink.line} horizontal={false} />
          <XAxis type="number" tick={{ fill: ink.muted, fontSize: 11 }} />
          <YAxis type="category" dataKey="symbol" tick={{ fill: ink.muted, fontSize: 11 }} width={120} />
          <Tooltip />
          <Bar dataKey="notional" fill={ink.accent} name="Notional" />
        </BarChart>
      </ChartCanvas>
    </ChartFrame>
  );
}

export function WinLossChart({ wins, losses }: { wins: number; losses: number }) {
  const ink = useInk();
  const rows = [
    { name: "Wins", value: wins },
    { name: "Losses", value: losses },
  ];
  return (
    <ChartFrame title="Win/loss distribution" empty={wins + losses === 0}>
      <ChartCanvas>
        <PieChart>
          <Pie data={rows} dataKey="value" nameKey="name" innerRadius={48} outerRadius={80}>
            <Cell fill={ink.profit} />
            <Cell fill={ink.loss} />
          </Pie>
          <Tooltip />
        </PieChart>
      </ChartCanvas>
    </ChartFrame>
  );
}

function ChartFrame({ title, empty = false, children }: { title: string; empty?: boolean; children: ReactNode }) {
  return (
    <section className="bg-panel border border-line rounded-lg p-3">
      <h2 className="text-sm text-muted mb-2">{title}</h2>
      {empty ? <div className="h-[220px] grid place-items-center text-sm text-muted">No points for this diagram yet.</div> : children}
    </section>
  );
}
