"use client";

import { useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Account = { id: string; display_name: string; account_number: string; currency: string };
type Trade = {
  ticket: string;
  symbol: string;
  direction: string;
  lot: string;
  entry: string;
  close_price: string | null;
  profit: string;
  status: string;
  close_time: string | null;
  source?: string;
};
type Day = { date: string; net: string; result: "profit" | "loss" | "even"; trade_count: number; trades: Trade[] };
type Source = { source: string; net: string; trades: number; result: "profit" | "loss" | "even" };
type Journal = {
  account_name: string;
  currency: string;
  error: string;
  summary: { profitable_days: number; loss_days: number; even_days: number; net: string; trades: number };
  sources: Source[];
  days: Day[];
};

export default function JournalPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");
  const [journal, setJournal] = useState<Journal | null>(null);
  const [selected, setSelected] = useState("");
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()));
  const [error, setError] = useState("");

  useEffect(() => {
    apiJson<Account[]>("/api/v1/journal/accounts")
      .then((rows) => {
        setAccounts(rows);
        if (rows[0]) setAccountId(rows[0].id);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!accountId) return;
    let stopped = false;
    setJournal(null);
    apiJson<Journal>(`/api/v1/journal?account_id=${accountId}`)
      .then((body) => {
        if (stopped) return;
        setJournal(body);
        const newest = body.days[0]?.date ? dayKey(body.days[0].date) : "";
        setSelected(newest);
        setCursor(newest ? monthOf(newest) : startOfMonth(new Date()));
        setError("");
      })
      .catch((err: Error) => {
        if (!stopped) setError(err.message);
      });
    return () => {
      stopped = true;
    };
  }, [accountId]);

  const day = journal?.days.find((item) => dayKey(item.date) === selected);

  return (
    <div>
      <PageTitle title="Journal" detail="A month calendar of closed and open trades. Green days made money, red days lost money." />
      <label className="block max-w-md mb-5 text-sm">
        <span className="text-muted">Account</span>
        <select className="mt-1" value={accountId} onChange={(event) => setAccountId(event.target.value)}>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>{account.display_name} · {account.account_number}</option>
          ))}
        </select>
      </label>
      {error ? <p className="text-loss mb-3">{error}</p> : null}
      {journal?.error ? <p className="text-loss mb-3 text-sm">{journal.error}</p> : null}
      {journal ? (
        <>
          <section className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
            <Card label="Profitable days" value={String(journal.summary.profitable_days)} tone="good" />
            <Card label="Loss days" value={String(journal.summary.loss_days)} tone="bad" />
            <Card label="Even days" value={String(journal.summary.even_days)} />
            <Card label="Net" value={`${signed(journal.summary.net)} ${journal.currency}`} tone={toneOf(journal.summary.net)} />
            <Card label="Trades" value={String(journal.summary.trades)} tone="accent" />
          </section>
          <Calendar
            cursor={cursor}
            days={journal.days}
            selected={selected}
            currency={journal.currency}
            onSelect={setSelected}
            onShift={(delta) => setCursor((current) => new Date(current.getFullYear(), current.getMonth() + delta, 1))}
            onJump={(iso) => setCursor(monthOf(iso))}
          />
          {day ? (
            <section className="book overflow-x-auto mt-4">
              <h2 className="px-3 py-2 text-sm">{formatDay(day.date)} · {signed(day.net)} {journal.currency}</h2>
              <table className="w-full text-sm">
                <thead className="text-left text-muted">
                  <tr>{["Ticket", "Symbol", "Side", "Lot", "Entry", "Close", "P/L", "Source", "Status"].map((head) => <th key={head} className="px-3 py-2">{head}</th>)}</tr>
                </thead>
                <tbody>
                  {day.trades.map((trade) => (
                    <tr key={`${trade.status}-${trade.ticket}`} className="border-t border-line">
                      <td className="px-3 py-2 num">{trade.ticket}</td>
                      <td className="px-3 py-2">{trade.symbol}</td>
                      <td className="px-3 py-2"><span className={`pill ${trade.direction === "sell" ? "sell" : "buy"}`}>{trade.direction}</span></td>
                      <td className="px-3 py-2 num">{trade.lot}</td>
                      <td className="px-3 py-2 num">{trade.entry}</td>
                      <td className="px-3 py-2 num">{trade.close_price ?? "—"}</td>
                      <td className={`px-3 py-2 num ${moneyClass(trade.profit)}`}>{signed(trade.profit)}</td>
                      <td className="px-3 py-2">{trade.source || "—"}</td>
                      <td className="px-3 py-2">{trade.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
        </>
      ) : accountId ? <p className="text-muted">Loading journal…</p> : null}
    </div>
  );
}

function Card({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <article className={`metric ${tone}`}>
      <div className="label">{label}</div>
      <div className={`value num text-lg ${tone === "good" ? "pos" : ""} ${tone === "bad" ? "neg" : ""}`}>{value}</div>
    </article>
  );
}

function signed(value: string) {
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const text = number.toFixed(2);
  return number > 0 ? `+${text}` : text;
}

function toneOf(value: string) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "";
  return number > 0 ? "good" : "bad";
}

function moneyClass(value: string) {
  const number = Number(value);
  if (!Number.isFinite(number) || number === 0) return "";
  return number > 0 ? "pos" : "neg";
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function Calendar({ cursor, days, selected, currency, onSelect, onShift, onJump }: {
  cursor: Date;
  days: Day[];
  selected: string;
  currency: string;
  onSelect: (date: string) => void;
  onShift: (delta: number) => void;
  onJump: (iso: string) => void;
}) {
  const byDate = new Map(days.map((item) => [dayKey(item.date), item]));
  const cells = monthCells(cursor);
  const title = cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const prefix = isoDate(cursor.getFullYear(), cursor.getMonth(), 1).slice(0, 7);
  const inMonth = days.filter((item) => dayKey(item.date).startsWith(prefix));
  const newest = days[0] ? dayKey(days[0].date) : "";
  return (
    <section className="cal">
      <div className="cal-head">
        <h2>{title}</h2>
        <div className="cal-nav">
          <button className="ghost" type="button" onClick={() => onShift(-1)}>Previous</button>
          <button className="ghost" type="button" onClick={() => onShift(1)}>Next</button>
        </div>
      </div>
      {inMonth.length === 0 && newest ? (
        <p className="text-sm text-muted mb-3">
          No trades in {title}.{" "}
          <button className="ghost" type="button" onClick={() => onJump(newest)}>Open {formatDay(newest)}</button>
        </p>
      ) : null}
      <div className="cal-grid" style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))" }}>
        {WEEKDAYS.map((name) => <div key={name} className="cal-dow">{name}</div>)}
        {cells.map((dayNumber, index) => {
          if (dayNumber === null) return <div key={`pad-${index}`} className="cal-pad" />;
          const date = isoDate(cursor.getFullYear(), cursor.getMonth(), dayNumber);
          const item = byDate.get(date);
          const trades = item?.trades || [];
          return (
            <button
              key={date}
              type="button"
              className={`cal-day ${item?.result || "blank"} ${selected === date ? "on" : ""}`}
              onClick={() => onSelect(date)}
            >
              <span className="when">{dayNumber}</span>
              {item ? <span className={`day-net num ${moneyClass(item.net)}`}>{signed(item.net)} {currency}</span> : null}
              {trades.length ? (
                <span className="day-trades">
                  {trades.slice(0, 3).map((trade) => (
                    <span key={`${trade.status}-${trade.ticket}`} className="day-line">
                      <span>{trade.symbol}</span>
                      <span className={`num ${moneyClass(trade.profit)}`}>{signed(trade.profit)}</span>
                    </span>
                  ))}
                  {trades.length > 3 ? <span className="more">+{trades.length - 3} more</span> : null}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      <div className="cal-key">
        <span><i className="profit" />Profit day</span>
        <span><i className="loss" />Loss day</span>
      </div>
    </section>
  );
}

function dayKey(value: string) {
  return value.slice(0, 10);
}

function formatDay(iso: string) {
  const [year, month, day] = dayKey(iso).split("-").map(Number);
  return new Date(year, (month || 1) - 1, day || 1).toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" });
}

function startOfMonth(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1);
}

function monthOf(iso: string) {
  const [year, month] = iso.split("-").map(Number);
  return new Date(year, (month || 1) - 1, 1);
}

function isoDate(year: number, month: number, day: number) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function monthCells(cursor: Date) {
  const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
  const startOffset = (first.getDay() + 6) % 7;
  const count = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate();
  const cells: (number | null)[] = [];
  for (let index = 0; index < startOffset; index += 1) cells.push(null);
  for (let day = 1; day <= count; day += 1) cells.push(day);
  while (cells.length % 7 !== 0) cells.push(null);
  return cells;
}
