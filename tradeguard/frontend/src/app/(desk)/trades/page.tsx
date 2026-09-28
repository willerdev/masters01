"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Row = Record<string, string | number | null>;
type SyncError = { account: string; detail: string };
type Book = { trades: Row[]; errors: SyncError[]; synced_at?: string | null };

const COLUMNS: [string, string][] = [
  ["account_name", "Account"],
  ["ticket", "Ticket"],
  ["symbol", "Symbol"],
  ["direction", "Direction"],
  ["lot", "Lot"],
  ["entry", "Entry"],
  ["current_price", "Current"],
  ["floating_pl", "Floating P/L"],
  ["stop_loss", "Stop loss"],
  ["take_profit", "Take profit"],
  ["strategy", "Source"],
  ["magic_number", "Magic"],
];

type Account = { id: string; display_name: string; currency: string };

export default function TradesPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [errors, setErrors] = useState<SyncError[]>([]);
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState<Date | null>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [action, setAction] = useState("open");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    apiJson<Account[]>("/api/v1/accounts").then(setAccounts).catch(() => setAccounts([]));
  }, []);

  async function place(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const accountId = String(form.get("account_id") || "");
    try {
      const result = await apiJson<{ sent: boolean; decision: string; message: string }>(`/api/v1/accounts/${accountId}/orders`, {
        method: "POST",
        body: JSON.stringify({
          action,
          symbol: form.get("symbol"),
          side: form.get("side"),
          volume: form.get("volume"),
          price: action === "limit" ? form.get("price") : null,
          stop_loss: form.get("stop_loss") || null,
          take_profit: form.get("take_profit") || null,
        }),
      });
      setNotice(result.sent ? `Sent. ${result.message}` : `${result.decision}. ${result.message}`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Order was not sent");
    }
  }

  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const load = async () => {
      try {
        const body = await apiJson<Book>("/api/v1/trades");
        if (stopped) return;
        setRows(body.trades || []);
        setErrors(body.errors || []);
        setError("");
        setAsOf(body.synced_at ? new Date(body.synced_at) : new Date());
      } catch (err) {
        if (!stopped) setError(err instanceof Error ? err.message : "Open trades could not be loaded");
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
      <div className="flex flex-wrap items-end justify-between gap-3">
        <PageTitle title="Trades" detail="Open trades on connected accounts. The terminal is read every 2 seconds, and this page picks up the new price every second." />
        <div className="mb-5 flex items-center gap-2 text-sm text-muted">
          <span className="live-dot" />
          <span>Live · {asOf ? asOf.toLocaleTimeString() : "waiting"}</span>
        </div>
      </div>
      {accounts.length ? (
        <form className="grid md:grid-cols-4 gap-2 mb-5" onSubmit={place}>
          <select name="account_id" required defaultValue={accounts[0]?.id}>
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}
          </select>
          <input name="symbol" placeholder="Symbol" required />
          <input name="volume" type="number" min="0.01" step="0.01" placeholder="Volume" required />
          <select name="side" defaultValue="buy"><option value="buy">Buy</option><option value="sell">Sell</option></select>
          <select name="action" value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="open">Market trade</option>
            <option value="limit">Limit order</option>
          </select>
          {action === "limit" ? <input name="price" type="number" step="0.00001" min="0" placeholder="Limit price" required /> : null}
          <input name="stop_loss" type="number" step="0.00001" placeholder="Stop" />
          <input name="take_profit" type="number" step="0.00001" placeholder="Target" />
          <button className="primary" type="submit">{action === "limit" ? "Place limit" : "Place trade"}</button>
        </form>
      ) : null}
      {notice ? <p className="text-sm mb-3">{notice}</p> : null}
      {error ? <p className="text-loss mb-3">{error}</p> : null}
      {errors.map((item) => (
        <p key={item.account} className="text-loss mb-2 text-sm">{item.account}: {item.detail}</p>
      ))}
      <div className="book overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr>{COLUMNS.map(([, label]) => <th key={label} className="px-3 py-2 whitespace-nowrap">{label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.account_id}-${row.ticket}`} className="border-t border-line">
                {COLUMNS.map(([key]) => <td key={key} className={`px-3 py-2 whitespace-nowrap ${cellClass(key, row)}`}>{cellText(key, row)}</td>)}
              </tr>
            ))}
            {rows.length === 0 ? <tr><td className="px-3 py-6 text-muted" colSpan={COLUMNS.length}>No open trades on connected accounts.</td></tr> : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function cellText(key: string, row: Row) {
  const value = row[key];
  if (value == null || value === "") return "—";
  if (key === "floating_pl") {
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    const text = number.toFixed(2);
    return number > 0 ? `+${text}` : text;
  }
  return String(value);
}

function cellClass(key: string, row: Row) {
  if (key === "direction") {
    return String(row.direction).toLowerCase() === "sell" ? "neg" : "pos";
  }
  if (key === "floating_pl") {
    const number = Number(row.floating_pl);
    if (!Number.isFinite(number) || number === 0) return "num";
    return number > 0 ? "num pos" : "num neg";
  }
  if (key === "ticket" || key === "lot" || key === "entry" || key === "current_price" || key === "magic_number") return "num";
  return "";
}
