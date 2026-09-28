"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AccountSections, accountBody, type ConnectionMethod, type Probe } from "@/components/AccountSections";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Created = {
  id: string;
  webhook?: { url_path: string; api_key: string; signing_secret: string };
};

export default function NewAccountPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [method, setMethod] = useState<ConnectionMethod>("metaapi");
  const [probe, setProbe] = useState<Probe | null>(null);
  const [created, setCreated] = useState<Created | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      const body = await apiJson<Created>("/api/v1/accounts", {
        method: "POST",
        body: JSON.stringify(accountBody(form, method, probe)),
      });
      setCreated(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create account");
    }
  }

  return (
    <div className="max-w-3xl">
      <PageTitle title="Add account" detail="Choose a connection. Account name, number, broker, and size are read after the live check succeeds." />
      {error ? <p className="text-loss mb-3">{error}</p> : null}
      {created?.webhook ? (
        <div className="bg-panel border border-line rounded-lg p-4 text-sm">
          <p className="mb-2">Copy these webhook credentials now. They are not shown again.</p>
          <p className="num break-all">Path: {created.webhook.url_path}</p>
          <p className="num break-all mt-2">API key: {created.webhook.api_key}</p>
          <p className="num break-all mt-2">Signing secret: {created.webhook.signing_secret}</p>
          <button className="primary mt-4" onClick={() => router.push(`/accounts/${created.id}`)}>Open account</button>
        </div>
      ) : created ? (
        <div className="bg-panel border border-line rounded-lg p-4 text-sm">
          <p>Account saved. Broker passwords and API tokens stay encrypted.</p>
          <button className="primary mt-4" onClick={() => router.push(`/accounts/${created.id}`)}>Open account</button>
        </div>
      ) : (
        <form className="flex flex-col gap-4" onSubmit={onSubmit}>
          <AccountSections method={method} onMethod={setMethod} allowWebhook onProbe={setProbe} />
          <button className="primary" type="submit" disabled={method !== "webhook" && !probe?.ok}>Save account</button>
        </form>
      )}
    </div>
  );
}
