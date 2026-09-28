"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type KeyRow = { id: string; name: string; prefix: string; revoked: boolean };

export default function ApiKeysPage() {
  const [rows, setRows] = useState<KeyRow[]>([]);
  const [created, setCreated] = useState("");
  const [error, setError] = useState("");

  function load() {
    apiJson<KeyRow[]>("/api/v1/api-keys").then(setRows).catch((err: Error) => setError(err.message));
  }

  useEffect(() => {
    load();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const body = await apiJson<{ api_key: string }>("/api/v1/api-keys", { method: "POST", body: JSON.stringify({ name: form.get("name"), scopes: ["accounts.read"] }) });
    setCreated(body.api_key);
    load();
  }

  return (
    <div className="max-w-xl">
      <PageTitle title="API keys" detail="The raw key is shown once. Stored value is a hash." />
      {error ? <p className="text-loss">{error}</p> : null}
      <form className="flex gap-2 mb-4" onSubmit={onSubmit}>
        <input name="name" placeholder="Key name" required />
        <button className="primary" type="submit">Create</button>
      </form>
      {created ? <p className="num text-sm break-all mb-4">{created}</p> : null}
      <ul className="text-sm">
        {rows.map((row) => <li key={row.id} className="border-b border-line py-2">{row.name} · {row.prefix} · {row.revoked ? "revoked" : "active"}</li>)}
      </ul>
    </div>
  );
}
