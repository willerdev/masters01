"use client";

import { FormEvent, useEffect, useState } from "react";
import { PageTitle } from "@/components/Shell";
import { apiJson } from "@/lib/api";

type Application = {
  id: string;
  kind: string;
  status: string;
  email: string;
  full_name: string;
  flags: string[];
  answers: Record<string, unknown>;
  review_note: string;
};
type Capital = { id: string; email: string; fund: string; kind: string; amount: string; status: string };
type Account = { id: string; display_name: string };

export default function ApplicationsPage() {
  const [code, setCode] = useState("");
  const [applications, setApplications] = useState<Application[]>([]);
  const [requests, setRequests] = useState<Capital[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [message, setMessage] = useState("");

  function load() {
    apiJson<{ code: string }>("/api/v1/join-code").then((body) => setCode(body.code)).catch((error: Error) => setMessage(error.message));
    apiJson<{ applications: Application[]; capital_requests: Capital[] }>("/api/v1/applications")
      .then((body) => {
        setApplications(body.applications);
        setRequests(body.capital_requests);
      })
      .catch((error: Error) => setMessage(error.message));
    apiJson<Account[]>("/api/v1/accounts").then(setAccounts).catch(() => undefined);
  }

  useEffect(() => {
    load();
  }, []);

  async function review(id: string, decision: string, note: string, accountId: string) {
    try {
      await apiJson(`/api/v1/applications/${id}`, {
        method: "POST",
        body: JSON.stringify({ decision, note, account_id: accountId || null }),
      });
      setMessage(decision === "approve" ? "Approved. They can sign in to their portal." : "Rejected.");
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Review failed");
    }
  }

  async function reviewCapital(id: string, decision: string) {
    try {
      await apiJson(`/api/v1/capital-requests/${id}`, { method: "POST", body: JSON.stringify({ decision, note: "" }) });
      setMessage(decision === "approve" ? "Capital request approved at the locked NAV." : "Capital request rejected.");
      load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Review failed");
    }
  }

  return (
    <div className="max-w-5xl">
      <PageTitle title="Applications" detail="Share the join code. Nothing is opened until you approve the person, and investor money is only recorded when you approve the request." />
      {message ? <p className="text-sm mb-4">{message}</p> : null}
      <div className="flex items-center gap-3 mb-6">
        <div className="text-sm">Join code <span className="num font-semibold">{code}</span></div>
        <button className="ghost" type="button" onClick={() => apiJson<{ code: string }>("/api/v1/join-code/rotate", { method: "POST" }).then((body) => setCode(body.code))}>New code</button>
      </div>
      <section className="mb-8">
        <h2 className="mb-2">People</h2>
        {applications.map((row) => (
          <ApplicationCard key={row.id} row={row} accounts={accounts} onReview={review} />
        ))}
      </section>
      <section>
        <h2 className="mb-2">Capital requests</h2>
        {requests.map((row) => (
          <article key={row.id} className="border border-line bg-panel rounded p-3 mb-2 text-sm flex justify-between gap-3">
            <div>{row.email} · {row.kind} {row.amount} · {row.fund} · {row.status}</div>
            {row.status === "pending" ? (
              <div className="flex gap-2">
                <button className="primary" type="button" onClick={() => void reviewCapital(row.id, "approve")}>Approve</button>
                <button className="ghost" type="button" onClick={() => void reviewCapital(row.id, "reject")}>Reject</button>
              </div>
            ) : null}
          </article>
        ))}
      </section>
    </div>
  );
}

function ApplicationCard({ row, accounts, onReview }: { row: Application; accounts: Account[]; onReview: (id: string, decision: string, note: string, accountId: string) => void }) {
  const [accountId, setAccountId] = useState("");
  const [note, setNote] = useState("");

  function submit(event: FormEvent<HTMLFormElement>, decision: string) {
    event.preventDefault();
    onReview(row.id, decision, note, accountId);
  }

  return (
    <article className="border border-line bg-panel rounded p-3 mb-3">
      <div className="flex justify-between gap-3">
        <div>
          <div className="font-medium">{row.full_name} · {row.kind}</div>
          <div className="text-sm text-muted">{row.email} · {row.status}</div>
        </div>
        <div className="text-xs text-loss">{row.flags.join(" · ")}</div>
      </div>
      <dl className="grid md:grid-cols-2 gap-x-4 text-sm mt-3">
        {Object.entries(row.answers).map(([key, value]) => (
          <div key={key} className="flex justify-between gap-3 border-b border-line py-1">
            <dt className="text-muted">{key.replaceAll("_", " ")}</dt>
            <dd className="text-right">{Array.isArray(value) ? value.join(", ") : String(value)}</dd>
          </div>
        ))}
      </dl>
      {row.status === "pending" ? (
        <form className="grid md:grid-cols-4 gap-2 mt-3" onSubmit={(event) => submit(event, "approve")}>
          {row.kind === "trader" ? (
            <select value={accountId} onChange={(event) => setAccountId(event.target.value)}>
              <option value="">Assign an account later</option>
              {accounts.map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}
            </select>
          ) : <div />}
          <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Note to the applicant" />
          <button className="primary" type="submit">Approve</button>
          <button className="ghost" type="button" onClick={() => onReview(row.id, "reject", note, "")}>Reject</button>
        </form>
      ) : row.review_note ? <p className="text-sm mt-2">{row.review_note}</p> : null}
    </article>
  );
}
