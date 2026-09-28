"use client";

import { FormEvent, useEffect, useState } from "react";
import { AssetPanel } from "@/components/AssetPanel";
import { PortalFrame } from "@/components/PortalFrame";
import { apiJson } from "@/lib/api";

type Fund = { id: string; name: string; currency: string; unit_price: string | null; units: string; capital_paid: string };
type RequestRow = { id: string; fund: string; kind: string; amount: string; status: string; review_note: string };
type Wallet = { id: string; fund_id: string; fund: string; label: string; address: string; currency: string; available: string };
type Move = { id: string; label: string; direction: string; amount: string; currency: string; status: string; note: string };

export default function InvestorPortal() {
  const [funds, setFunds] = useState<Fund[]>([]);
  const [requests, setRequests] = useState<RequestRow[]>([]);
  const [wallets, setWallets] = useState<Wallet[]>([]);
  const [moves, setMoves] = useState<Move[]>([]);
  const [message, setMessage] = useState("");

  function load() {
    apiJson<{ funds: Fund[]; requests: RequestRow[]; wallets: Wallet[]; wallet_movements: Move[] }>("/api/v1/portal/investor")
      .then((body) => {
        setFunds(body.funds);
        setRequests(body.requests);
        setWallets(body.wallets || []);
        setMoves(body.wallet_movements || []);
      })
      .catch((error: Error) => setMessage(error.message));
  }

  useEffect(() => {
    load();
  }, []);

  async function saveWallet(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await apiJson("/api/v1/portal/investor/wallets", {
        method: "POST",
        body: JSON.stringify({ fund_id: form.get("fund_id"), label: form.get("label"), address: form.get("address") }),
      });
      setMessage("Wallet address saved.");
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Wallet was not saved");
    }
  }

  async function moveCash(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const walletId = String(form.get("wallet_id") || "");
    try {
      await apiJson(`/api/v1/portal/investor/wallets/${walletId}/moves`, {
        method: "POST",
        body: JSON.stringify({ direction: form.get("direction"), amount: form.get("amount"), note: form.get("note") || "" }),
      });
      setMessage("Sent. A deposit is available only after an admin posts it. A withdrawal cannot exceed the available balance.");
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Wallet movement was not sent");
    }
  }

  async function ask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await apiJson("/api/v1/portal/investor/requests", {
        method: "POST",
        body: JSON.stringify({ fund_id: form.get("fund_id"), kind: form.get("kind"), amount: form.get("amount") }),
      });
      setMessage("Request sent. Units change only after an admin approves it.");
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Request was not sent");
    }
  }

  return (
    <PortalFrame title="Investor portal">
      <div className="mb-8">
        <AssetPanel />
      </div>
      <h1 className="text-2xl font-semibold mb-2">Your holding</h1>
      <p className="text-sm text-muted mb-4">Prices come from the latest locked NAV. A request does not move broker cash.</p>
      {message ? <p className="text-sm mb-4">{message}</p> : null}
      <div className="flex flex-col gap-3 mb-6">
        {funds.map((fund) => (
          <article key={fund.id} className="border border-line bg-panel rounded p-3">
            <div className="font-medium">{fund.name}</div>
            <div className="text-sm num text-muted">Unit price {fund.unit_price ?? "not published"} {fund.currency} · your units {fund.units} · paid {fund.capital_paid}</div>
          </article>
        ))}
      </div>
      <form className="grid md:grid-cols-4 gap-2 mb-6" onSubmit={ask}>
        <select name="fund_id" required defaultValue="">
          <option value="" disabled>Fund</option>
          {funds.map((fund) => <option key={fund.id} value={fund.id}>{fund.name}</option>)}
        </select>
        <select name="kind" defaultValue="subscribe">
          <option value="subscribe">Subscribe</option>
          <option value="redeem">Redeem</option>
        </select>
        <input name="amount" type="number" min="0.01" step="0.01" placeholder="Amount" required />
        <button className="primary" type="submit">Request</button>
      </form>
      <h2 className="mb-2">Wallet</h2>
      <p className="text-sm text-muted mb-3">Deposit and withdraw against a saved address. You can withdraw only the cash already posted to that wallet. This does not move broker equity.</p>
      <form className="grid md:grid-cols-4 gap-2 mb-3" onSubmit={saveWallet}>
        <select name="fund_id" required defaultValue="">
          <option value="" disabled>Fund</option>
          {funds.map((fund) => <option key={fund.id} value={fund.id}>{fund.name}</option>)}
        </select>
        <input name="label" placeholder="Wallet name" required />
        <input name="address" placeholder="Wallet address" required />
        <button className="ghost" type="submit">Save address</button>
      </form>
      {wallets.map((wallet) => (
        <article key={wallet.id} className="border border-line bg-panel rounded p-3 mb-2 text-sm">
          <div className="font-medium">{wallet.label} · {wallet.fund}</div>
          <div className="num text-muted">{wallet.address}</div>
          <div className="num mt-1">Available {wallet.available} {wallet.currency}</div>
        </article>
      ))}
      {wallets.length ? (
        <form className="grid md:grid-cols-4 gap-2 mb-6" onSubmit={moveCash}>
          <select name="wallet_id" required defaultValue={wallets[0]?.id}>
            {wallets.map((wallet) => <option key={wallet.id} value={wallet.id}>{wallet.label} · {wallet.available} {wallet.currency}</option>)}
          </select>
          <select name="direction" defaultValue="deposit">
            <option value="deposit">Deposit</option>
            <option value="withdraw">Withdraw</option>
          </select>
          <input name="amount" type="number" min="0.01" step="0.01" placeholder="Amount" required />
          <button className="primary" type="submit">Send</button>
        </form>
      ) : null}
      <ul className="text-sm mb-6">
        {moves.map((row) => (
          <li key={row.id} className="border-b border-line py-2">{row.direction} {row.amount} {row.currency} · {row.label} · {row.status}{row.note ? ` · ${row.note}` : ""}</li>
        ))}
      </ul>
      <h2 className="mb-2">Requests</h2>
      <ul className="text-sm">
        {requests.map((row) => (
          <li key={row.id} className="border-b border-line py-2">{row.kind} {row.amount} {row.fund} · {row.status}{row.review_note ? ` · ${row.review_note}` : ""}</li>
        ))}
      </ul>
    </PortalFrame>
  );
}
