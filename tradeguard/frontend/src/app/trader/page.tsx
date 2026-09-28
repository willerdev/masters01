"use client";

import { FormEvent, useEffect, useState } from "react";
import { PortalFrame } from "@/components/PortalFrame";
import { apiJson } from "@/lib/api";

type Position = { ticket: string; symbol: string; side: string; volume: string; profit: string };
type Account = { id: string; name: string; currency: string; equity: string | null; control_state: string; positions: Position[] };
type Limits = { name: string; max_positions: number; risk_per_trade_pct: string; daily_loss_pct: string; max_drawdown_pct: string };

export default function TraderPortal() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [action, setAction] = useState("open");
  const [message, setMessage] = useState("");

  function load() {
    apiJson<{ accounts: Account[]; limits: Limits | null }>("/api/v1/portal/trader")
      .then((body) => {
        setAccounts(body.accounts);
        setLimits(body.limits);
      })
      .catch((error: Error) => setMessage(error.message));
  }

  useEffect(() => {
    load();
  }, []);

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const accountId = String(form.get("account_id") || "");
    try {
      const result = await apiJson<{ sent: boolean; decision: string; message: string }>(`/api/v1/accounts/${accountId}/orders`, {
        method: "POST",
        body: JSON.stringify({
          action: form.get("action"),
          symbol: form.get("symbol"),
          side: form.get("side"),
          volume: form.get("volume"),
          stop_loss: form.get("stop_loss") || null,
          take_profit: form.get("take_profit") || null,
          price: action === "limit" ? form.get("price") : null,
        }),
      });
      setMessage(result.sent ? `Sent. ${result.message}` : `${result.decision}. ${result.message}`);
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Order was not sent");
    }
  }

  return (
    <PortalFrame title="Trader portal">
      <h1 className="text-2xl font-semibold mb-2">{limits?.name || "Trader"}</h1>
      {limits ? (
        <p className="text-sm text-muted mb-4">
          Limits agreed at approval: {limits.risk_per_trade_pct}% per trade, {limits.daily_loss_pct}% daily loss, {limits.max_drawdown_pct}% drawdown, {limits.max_positions} open positions.
        </p>
      ) : <p className="text-sm text-muted mb-4">Your profile is not on a book yet.</p>}
      {message ? <p className="text-sm mb-4">{message}</p> : null}
      {accounts.length === 0 ? <p className="text-sm">An admin has not assigned an account. You cannot see or send trades until they do.</p> : null}
      {accounts.map((account) => (
        <article key={account.id} className="border border-line bg-panel rounded p-3 mb-3">
          <div className="flex justify-between gap-3"><span>{account.name}</span><span className="num">{account.equity ?? "No equity"} {account.currency} · {account.control_state}</span></div>
          <ul className="text-sm mt-2">
            {account.positions.map((position) => <li key={position.ticket} className="num">{position.side} {position.symbol} {position.volume} · {position.profit}</li>)}
            {account.positions.length === 0 ? <li className="text-muted">No open trades</li> : null}
          </ul>
        </article>
      ))}
      {accounts.length > 0 ? (
        <form className="grid md:grid-cols-3 gap-2 mt-4" onSubmit={send}>
          <select name="account_id" required defaultValue={accounts[0]?.id}>
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
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
    </PortalFrame>
  );
}
