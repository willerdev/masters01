"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Account = { id: string; name: string; currency: string; equity: string | null; stale: boolean };
type Guideline = { id: string; name: string; action: string; value: string | null; measured: boolean; passed: boolean; operator: string; threshold: string };
type Investor = { id: string; name: string; email: string; units: string; capital_paid: string };
type Nav = { as_of: string; aum: string; unit_price: string; units_outstanding: string; locked: boolean };
type Fee = { kind: string; amount: string; created_at: string };
type Allocation = { account_id: string; volume: string; sent: boolean; decision: string; message: string };
type Order = { id: string; symbol: string; side: string; volume: string; status: string; allocations: Allocation[] };
type Recon = { account_id: string; status: string; detail: Record<string, unknown> };
type Wallet = { id: string; label: string; address: string; owner: string; investor: string; currency: string; available: string };
type WalletMove = { id: string; label: string; address: string; owner: string; direction: string; amount: string; currency: string; status: string; note: string };
type Fund = {
  id: string;
  name: string;
  base_currency: string;
  management_fee_pct: string;
  performance_fee_pct: string;
  snapshot: { aum: string; open_risk: string; unit_price: string; units_outstanding: string; accounts: Account[]; exposure: { symbol: string; mark: string; weight_pct: string | null }[]; blockers: string[]; publishable: boolean };
  guidelines: Guideline[];
  budget: string | null;
  nav: Nav[];
  investors: Investor[];
  fees: Fee[];
  orders: Order[];
  reconciliation: Recon[];
  accounts_available: { id: string; name: string; currency: string }[];
  wallets: Wallet[];
  movements: WalletMove[];
};

export default function FundPage() {
  const params = useParams<{ id: string }>();
  const [fund, setFund] = useState<Fund | null>(null);
  const [message, setMessage] = useState("");

  function load() {
    apiJson<Fund>(`/api/v1/funds/${params.id}`).then(setFund).catch((error: Error) => setMessage(error.message));
  }

  useEffect(() => {
    load();
  }, [params.id]);

  async function send(path: string, body?: unknown) {
    try {
      await apiJson(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
      setMessage("");
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request failed");
    }
  }

  if (!fund) {
    return <p className="text-muted">{message || "Loading fund…"}</p>;
  }

  const snap = fund.snapshot;

  return (
    <div className="flex flex-col gap-6 max-w-6xl">
      <PageTitle title={fund.name} detail="Equity is the sum of attached accounts. A subscription records units at the locked price and does not change the broker balance. Publish again after cash is actually in the accounts." />
      {message ? <p className="text-sm">{message}</p> : null}
      {snap.blockers.map((item) => <p key={item} className="text-sm text-loss">{item}</p>)}
      <section>
        <h2 className="mb-2">Wallets</h2>
        <p className="text-sm text-muted mb-3">Cash at a saved address. A deposit or withdrawal here does not change broker equity or investor units.</p>
        <form className="grid md:grid-cols-4 gap-2 mb-3" onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          void send(`/api/v1/funds/${fund.id}/wallets`, { label: form.get("label"), address: form.get("address") });
        }}>
          <input name="label" placeholder="Wallet name" required />
          <input name="address" placeholder="Wallet address" required className="md:col-span-2" />
          <button className="primary" type="submit">Save address</button>
        </form>
        {(fund.wallets || []).filter((wallet) => wallet.owner === "fund").length === 0 ? <p className="text-sm text-muted mb-3">No wallet saved yet.</p> : null}
        {(fund.wallets || []).filter((wallet) => wallet.owner === "fund").map((wallet) => (
          <form key={wallet.id} className="border border-line bg-panel rounded p-3 mb-2" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/wallets/${wallet.id}/moves`, { direction: form.get("direction"), amount: form.get("amount"), note: form.get("note") || "" });
          }}>
            <div className="text-sm mb-2"><span className="font-medium">{wallet.label}</span> · <span className="num break-all">{wallet.address}</span></div>
            <div className="text-sm num mb-2">Available {wallet.available} {wallet.currency}</div>
            <div className="grid md:grid-cols-4 gap-2">
              <select name="direction" defaultValue="deposit"><option value="deposit">Deposit</option><option value="withdraw">Withdraw</option></select>
              <input name="amount" type="number" min="0.01" step="0.01" placeholder="Amount" required />
              <input name="note" placeholder="Note" />
              <button className="primary" type="submit">Record</button>
            </div>
          </form>
        ))}
        {(fund.movements || []).filter((row) => row.owner === "investor" && row.status === "pending").map((row) => (
          <div key={row.id} className="flex flex-wrap items-center gap-2 border border-line rounded px-3 py-2 mb-2 text-sm">
            <span className="flex-1">{row.direction} {row.amount} {row.currency} · {row.label} · <span className="num">{row.address}</span></span>
            <button className="primary" type="button" onClick={() => void send(`/api/v1/funds/${fund.id}/wallet-moves/${row.id}`, { decision: "post" })}>Post</button>
            <button className="ghost" type="button" onClick={() => void send(`/api/v1/funds/${fund.id}/wallet-moves/${row.id}`, { decision: "reject" })}>Reject</button>
          </div>
        ))}
      </section>

      <section className="grid md:grid-cols-4 gap-3">
        <article className="metric"><div className="label">Equity</div><div className="value num">{snap.aum} {fund.base_currency}</div></article>
        <article className="metric"><div className="label">Unit price</div><div className="value num">{snap.unit_price}</div></article>
        <article className="metric"><div className="label">Units</div><div className="value num">{snap.units_outstanding}</div></article>
        <article className="metric"><div className="label">Open risk</div><div className="value num">{snap.open_risk}</div></article>
      </section>

      <section className="grid xl:grid-cols-2 gap-6">
        <div>
          <h2 className="mb-2">Accounts</h2>
          <form className="flex gap-2 mb-3" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/accounts`, { account_id: form.get("account_id") });
          }}>
            <select name="account_id" required defaultValue="">
              <option value="" disabled>Attach an account</option>
              {fund.accounts_available.map((account) => <option key={account.id} value={account.id}>{account.name} · {account.currency}</option>)}
            </select>
            <button className="primary" type="submit">Attach</button>
          </form>
          <ul className="border border-line rounded bg-panel">
            {snap.accounts.map((account) => (
              <li key={account.id} className="flex justify-between gap-3 px-3 py-2 border-b border-line last:border-b-0">
                <span>{account.name}</span>
                <span className="num">{account.equity ?? "No equity"} {account.currency}{account.stale ? " · stale" : ""}</span>
              </li>
            ))}
          </ul>
          <button className="primary mt-3" type="button" onClick={() => void send(`/api/v1/funds/${fund.id}/nav`)}>Publish NAV</button>
        </div>
        <div>
          <h2 className="mb-2">Guidelines</h2>
          <ul className="flex flex-col gap-1 mb-3">
            {fund.guidelines.map((rule) => (
              <li key={rule.id} className="rounded px-3 py-2 text-sm" style={{ background: !rule.measured ? "var(--panel-2)" : rule.passed ? "var(--pass-bg)" : "var(--fail-bg)" }}>
                <div className="flex justify-between gap-3">
                  <span>{rule.name}</span>
                  <span>{rule.action}</span>
                </div>
                <div className="text-xs">{rule.measured ? `${rule.value} ${rule.operator} ${rule.threshold}` : "Needs equity before this can be checked"}</div>
              </li>
            ))}
          </ul>
          <form className="grid grid-cols-2 gap-2" onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/guidelines`, {
              name: form.get("name"),
              metric: form.get("metric"),
              operator: form.get("operator"),
              threshold: form.get("threshold"),
              action: form.get("action"),
            });
          }}>
            <input name="name" placeholder="Guideline name" required />
            <select name="metric" defaultValue="symbol_weight_pct">
              <option value="symbol_weight_pct">Largest symbol weight %</option>
              <option value="gross_exposure_pct">Gross exposure %</option>
              <option value="open_risk_pct">Open risk %</option>
            </select>
            <select name="operator" defaultValue=">">
              <option value=">">&gt;</option>
              <option value=">=">&gt;=</option>
              <option value="<">&lt;</option>
              <option value="<=">&lt;=</option>
            </select>
            <input name="threshold" type="number" step="0.01" placeholder="Limit" required />
            <select name="action" defaultValue="block">
              <option value="block">Block new orders</option>
              <option value="warn">Warn</option>
            </select>
            <button className="primary" type="submit">Save guideline</button>
          </form>
          <form className="flex gap-2 mt-3" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/budget`, { max_daily_risk_pct: form.get("max_daily_risk_pct") });
          }}>
            <input name="max_daily_risk_pct" type="number" step="0.01" min="0" placeholder={fund.budget ? `Open risk budget ${fund.budget}%` : "Open risk budget %"} required />
            <button className="ghost" type="submit">Save budget</button>
          </form>
        </div>
      </section>

      <section className="grid xl:grid-cols-2 gap-6">
        <div>
          <h2 className="mb-2">Investors</h2>
          <p className="text-sm text-muted mb-2">Use the locked unit price. To match the current book, subscribe an amount equal to equity at the opening price of 1.</p>
          <form className="grid grid-cols-3 gap-2 mb-3" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/subscriptions`, { name: form.get("name"), email: form.get("email"), amount: form.get("amount") });
          }}>
            <input name="name" placeholder="Name" required />
            <input name="email" type="email" placeholder="Email" required />
            <input name="amount" type="number" step="0.01" min="0" placeholder="Amount" required />
            <button className="primary" type="submit">Subscribe</button>
          </form>
          {fund.investors.map((investor) => (
            <form key={investor.id} className="flex items-center gap-2 border border-line bg-panel rounded px-3 py-2 mb-2 text-sm" onSubmit={(event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              void send(`/api/v1/funds/${fund.id}/redemptions`, { investor_id: investor.id, amount: form.get("amount") });
            }}>
              <div className="flex-1">
                <div>{investor.name}</div>
                <div className="text-muted">{investor.email} · {investor.units} units · paid {investor.capital_paid}</div>
              </div>
              <input name="amount" type="number" step="0.01" min="0" placeholder="Redeem amount" required />
              <button className="ghost" type="submit">Redeem</button>
            </form>
          ))}
        </div>
        <div>
          <h2 className="mb-2">NAV and fees</h2>
          <p className="text-sm text-muted mb-2">Fees are accrued here. They are not withdrawn from the broker. Management {fund.management_fee_pct}% / year, performance {fund.performance_fee_pct}%.</p>
          <button className="ghost mb-3" type="button" onClick={() => void send(`/api/v1/funds/${fund.id}/fees`)}>Accrue fees</button>
          <ul className="text-sm mb-3">
            {fund.nav.map((row) => <li key={row.as_of} className="num">Locked {row.as_of} · equity {row.aum} · price {row.unit_price} · units {row.units_outstanding}</li>)}
          </ul>
          <ul className="text-sm">
            {fund.fees.map((fee) => <li key={`${fee.created_at}-${fee.kind}`} className="num">{fee.kind} {fee.amount}</li>)}
          </ul>
        </div>
      </section>

      <section className="grid xl:grid-cols-2 gap-6">
        <div>
          <h2 className="mb-2">Fund order</h2>
          <p className="text-sm text-muted mb-2">Volume is split by account equity. Each slice still goes through the risk engine.</p>
          <form className="grid grid-cols-2 gap-2" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/orders`, {
              symbol: form.get("symbol"),
              side: form.get("side"),
              action: form.get("action"),
              volume: form.get("volume"),
              price: form.get("price") || null,
              stop_loss: form.get("stop_loss") || null,
              take_profit: form.get("take_profit") || null,
            });
          }}>
            <input name="symbol" placeholder="Symbol" required />
            <input name="volume" type="number" step="0.01" min="0" placeholder="Total volume" required />
            <select name="side" defaultValue="buy"><option value="buy">Buy</option><option value="sell">Sell</option></select>
            <select name="action" defaultValue="open"><option value="open">Market</option><option value="limit">Limit</option></select>
            <input name="price" type="number" step="0.00001" placeholder="Limit price" />
            <input name="stop_loss" type="number" step="0.00001" placeholder="Stop" />
            <input name="take_profit" type="number" step="0.00001" placeholder="Target" />
            <button className="primary" type="submit">Allocate</button>
          </form>
          {fund.orders.map((order) => (
            <article key={order.id} className="mt-3 text-sm border border-line bg-panel rounded p-3">
              <div>{order.side} {order.symbol} {order.volume} · {order.status}</div>
              {order.allocations.map((part) => <div key={part.account_id} className={part.sent ? "text-profit" : "text-loss"}>{part.volume} · {part.decision} · {part.message}</div>)}
            </article>
          ))}
        </div>
        <div>
          <h2 className="mb-2">Strategy, trader, and stop</h2>
          <form className="grid grid-cols-2 gap-2 mb-3" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/strategies`, { name: form.get("name"), symbols: form.get("symbols"), max_positions: Number(form.get("max_positions")), account_id: form.get("account_id") });
          }}>
            <input name="name" placeholder="Strategy" required />
            <input name="symbols" placeholder="Allowed symbols, comma separated" />
            <input name="max_positions" type="number" min="1" defaultValue="5" />
            <select name="account_id" required defaultValue="">
              <option value="" disabled>Account</option>
              {snap.accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </select>
            <button className="ghost" type="submit">Save strategy</button>
          </form>
          <form className="grid grid-cols-2 gap-2 mb-3" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/traders`, { name: form.get("name"), max_positions: Number(form.get("max_positions")), account_id: form.get("account_id") });
          }}>
            <input name="name" placeholder="Trader" required />
            <input name="max_positions" type="number" min="1" defaultValue="5" />
            <select name="account_id" required defaultValue="">
              <option value="" disabled>Account</option>
              {snap.accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
            </select>
            <button className="ghost" type="submit">Save trader</button>
          </form>
          <button className="ghost" type="button" onClick={() => void send(`/api/v1/funds/${fund.id}/reconcile`)}>Reconcile with broker</button>
          <ul className="text-sm mt-2 mb-4">
            {fund.reconciliation.map((row) => <li key={`${row.account_id}-${row.status}`}>{row.status}</li>)}
          </ul>
          <form className="flex gap-2" onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            void send(`/api/v1/funds/${fund.id}/stop`, { confirm: form.get("confirm") });
          }}>
            <input name="confirm" placeholder="Type STOP FUND" required />
            <button className="danger" type="submit">Stop fund</button>
          </form>
        </div>
      </section>

      <section>
        <h2 className="mb-2">Exposure</h2>
        <p className="text-sm text-muted mb-2">Mark is volume × price on the open book. It is the weight used by the guidelines.</p>
        <ul className="text-sm">
          {snap.exposure.map((row) => <li key={row.symbol} className="num">{row.symbol} · {row.mark} · {row.weight_pct ?? "—"}%</li>)}
        </ul>
      </section>
    </div>
  );
}
