"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Provider = { configured: boolean; provider: string; sandbox: boolean; enabled: boolean; callback_url: string };
type Payment = {
  id: string;
  provider: string;
  purpose: string;
  price_amount: string;
  price_currency: string;
  pay_currency: string;
  pay_amount: string | null;
  pay_address: string;
  invoice_url: string;
  provider_status: string;
  status: string;
  created_at: string;
};

export default function PaymentsPage() {
  const [provider, setProvider] = useState<Provider | null>(null);
  const [choice, setChoice] = useState("nowpayments");
  const [apiUrl, setApiUrl] = useState("https://api.nowpayments.io/v1");
  const [rows, setRows] = useState<Payment[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [created, setCreated] = useState<Payment | null>(null);

  function load() {
    return Promise.all([apiJson<Provider>("/api/v1/payments/provider"), apiJson<Payment[]>("/api/v1/payments")]).then(([config, payments]) => {
      setProvider(config);
      if (config.provider) setChoice(config.provider);
      setRows(payments);
    });
  }

  useEffect(() => {
    load().catch((err: Error) => setError(err.message));
  }, []);

  async function saveProvider(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    setMessage("");
    try {
      const body = await apiJson<Provider>("/api/v1/payments/provider", {
        method: "PUT",
        body: JSON.stringify({
          provider: choice,
          sandbox: form.get("sandbox") === "on",
          credentials: {
            api_key: form.get("api_key"),
            api_url: form.get("api_url"),
            ipn_secret: form.get("ipn_secret"),
            payout_email: form.get("payout_email"),
            payout_password: form.get("payout_password"),
            merchant_id: form.get("merchant_id"),
          },
        }),
      });
      setProvider(body);
      setMessage(body.configured ? `${body.provider} is connected. The API key is stored encrypted.` : "Provider was not saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Provider check failed");
    }
  }

  async function requestPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    setCreated(null);
    try {
      const body = await apiJson<Payment>("/api/v1/payments", {
        method: "POST",
        body: JSON.stringify({
          price_amount: form.get("price_amount"),
          price_currency: form.get("price_currency"),
          pay_currency: form.get("pay_currency"),
          purpose: form.get("purpose"),
          description: form.get("description"),
        }),
      });
      setCreated(body);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment request failed");
    }
  }

  return (
    <div className="max-w-5xl">
      <PageTitle
        title="Crypto payments"
        detail="Choose NOWPayments or Cryptomus. TradeGuard requests the payment from that provider and records paid only when the signed notification says so."
      />
      {error ? <p className="text-loss mb-3">{error}</p> : null}
      {message ? <p className="text-sm mb-3">{message}</p> : null}
      {!provider?.configured ? (
        <p className="mb-4 text-sm border border-line bg-panel rounded-lg px-3 py-3">
          No crypto provider is connected yet. Save NOWPayments or Cryptomus below. The check must succeed before the credentials are kept.
        </p>
      ) : (
        <p className="text-sm text-muted mb-4">
          Active provider: {provider.provider}
          {provider.sandbox ? " (sandbox)" : ""}. Callback {provider.callback_url}
        </p>
      )}
      <form className="flex flex-col gap-3 max-w-xl mb-8" onSubmit={saveProvider}>
        <div className="grid gap-2">
          <label className={`choice ${choice === "nowpayments" ? "on" : ""}`}>
            <input type="radio" checked={choice === "nowpayments"} onChange={() => setChoice("nowpayments")} />
            <span>NOWPayments</span>
          </label>
          <label className={`choice ${choice === "cryptomus" ? "on" : ""}`}>
            <input type="radio" checked={choice === "cryptomus"} onChange={() => setChoice("cryptomus")} />
            <span>Cryptomus</span>
          </label>
        </div>
        {choice === "cryptomus" ? <input name="merchant_id" placeholder="Merchant id" required autoComplete="off" /> : null}
        <input name="api_key" type="password" placeholder="API key" required autoComplete="off" />
        {choice === "nowpayments" ? (
          <>
            <input name="api_url" type="url" placeholder="API URL" required value={apiUrl} onChange={(event) => setApiUrl(event.target.value)} autoComplete="off" />
            <input name="payout_email" type="text" placeholder="Payout email, same as the dashboard" required autoComplete="username" />
            <input name="payout_password" type="password" placeholder="Payout password" required autoComplete="new-password" />
            <input name="ipn_secret" type="password" placeholder="IPN secret" required autoComplete="off" />
            <label className="text-sm flex gap-2 items-center">
              <input
                className="w-auto"
                type="checkbox"
                name="sandbox"
                onChange={(event) => setApiUrl(event.target.checked ? "https://api-sandbox.nowpayments.io/v1" : "https://api.nowpayments.io/v1")}
              />{" "}
              Sandbox API URL
            </label>
          </>
        ) : null}
        <button className="primary" type="submit">Check and save provider</button>
      </form>
      <form className="grid md:grid-cols-3 gap-3 max-w-4xl mb-8" onSubmit={requestPayment}>
        <input name="price_amount" type="number" min="0.01" step="0.01" placeholder="Amount" required />
        <input name="price_currency" defaultValue="USD" placeholder="Price currency" required />
        <input name="pay_currency" placeholder="Coin, optional (btc, USDT)" />
        <select name="purpose" defaultValue="deposit">
          <option value="deposit">Deposit</option>
          <option value="subscription">Subscription</option>
          <option value="other">Other</option>
        </select>
        <input name="description" placeholder="Description" />
        <button className="primary" type="submit" disabled={!provider?.configured}>Request payment</button>
      </form>
      {created ? (
        <p className="text-sm mb-4">
          Status {created.status}. Provider status {created.provider_status || "—"}.
          {created.invoice_url ? <> Checkout: {created.invoice_url}</> : null}
          {created.pay_address ? <> Address: <span className="num">{created.pay_address}</span></> : null}
        </p>
      ) : null}
      <table className="w-full text-sm bg-panel border border-line">
        <thead className="text-left text-muted">
          <tr>
            <th className="px-3 py-2">When</th>
            <th>Purpose</th>
            <th>Amount</th>
            <th>Status</th>
            <th>Provider</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-t border-line">
              <td className="px-3 py-2">{row.created_at.slice(0, 16).replace("T", " ")}</td>
              <td>{row.purpose}</td>
              <td className="num">{row.price_amount} {row.price_currency}</td>
              <td>{row.status}</td>
              <td>{row.provider_status || row.provider}</td>
            </tr>
          ))}
          {rows.length === 0 ? (
            <tr><td className="px-3 py-3 text-muted" colSpan={5}>No payment requests yet.</td></tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
