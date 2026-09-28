"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Recovery = {
  configured: boolean;
  email: string;
  trc20_wallet: string;
  next_of_kin_name: string;
  second_next_of_kin_name: string;
  password_set: boolean;
  updated_at: string | null;
  restored_at: string | null;
};

const EMPTY: Recovery = {
  configured: false,
  email: "",
  trc20_wallet: "",
  next_of_kin_name: "",
  second_next_of_kin_name: "",
  password_set: false,
  updated_at: null,
  restored_at: null,
};

export default function RecoveryPage() {
  const [record, setRecord] = useState<Recovery>(EMPTY);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    apiJson<Recovery>("/api/v1/recovery").then(setRecord).catch((err: Error) => setError(err.message));
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    setMessage("");
    try {
      const saved = await apiJson<Recovery>("/api/v1/recovery", {
        method: "PUT",
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
          confirm_password: form.get("confirm_password"),
          trc20_wallet: form.get("trc20_wallet"),
          next_of_kin_name: form.get("next_of_kin_name"),
          second_next_of_kin_name: form.get("second_next_of_kin_name"),
        }),
      });
      setRecord(saved);
      setMessage("Recovery details saved. The password is stored as a hash and is not shown again.");
      event.currentTarget.reset();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recovery details could not be saved");
    }
  }

  return (
    <div className="max-w-2xl">
      <PageTitle
        title="Account recovery"
        detail="If you lose the desk, the second next of kin can take management with this email, recovery password, TRC20 wallet, and both names."
      />
      {record.configured ? (
        <section className="mb-6 grid sm:grid-cols-2 gap-3">
          <article className="metric">
            <div className="label">Recovery email</div>
            <div className="value text-base">{record.email}</div>
          </article>
          <article className="metric accent">
            <div className="label">TRC20 wallet</div>
            <div className="value text-sm break-all">{record.trc20_wallet}</div>
          </article>
          <article className="metric">
            <div className="label">Next of kin</div>
            <div className="value text-base">{record.next_of_kin_name}</div>
          </article>
          <article className="metric good">
            <div className="label">Second next of kin</div>
            <div className="value text-base">{record.second_next_of_kin_name}</div>
          </article>
        </section>
      ) : (
        <p className="text-sm text-muted mb-4">No recovery record yet. The second next of kin cannot manage this desk until you save one.</p>
      )}
      {record.restored_at ? <p className="text-sm mb-4">Last restored {new Date(record.restored_at).toLocaleString()} by the second next of kin.</p> : null}
      <form className="flex flex-col gap-3" onSubmit={save}>
        <fieldset className="section">
          <legend>Recovery login</legend>
          <div className="grid gap-3">
            <input name="email" type="email" placeholder="Recovery email" defaultValue={record.email} required />
            <input name="password" type="password" placeholder="Recovery password" autoComplete="new-password" required />
            <input name="confirm_password" type="password" placeholder="Confirm recovery password" autoComplete="new-password" required />
            <input name="trc20_wallet" placeholder="TRC20 wallet address" defaultValue={record.trc20_wallet} required />
          </div>
        </fieldset>
        <fieldset className="section">
          <legend>Next of kin</legend>
          <div className="grid gap-3">
            <input name="next_of_kin_name" placeholder="Next of kin full name" defaultValue={record.next_of_kin_name} required />
            <input name="second_next_of_kin_name" placeholder="Second next of kin full name" defaultValue={record.second_next_of_kin_name} required />
            <p className="text-sm text-muted">The second next of kin is the person who can manage the desk after a successful recovery.</p>
          </div>
        </fieldset>
        {error ? <p className="text-sm text-loss">{error}</p> : null}
        {message ? <p className="text-sm text-profit">{message}</p> : null}
        <button className="primary" type="submit">{record.configured ? "Update recovery" : "Save recovery"}</button>
      </form>
    </div>
  );
}
