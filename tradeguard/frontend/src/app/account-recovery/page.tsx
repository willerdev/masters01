"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { apiJson } from "@/lib/api";
import { AuthCard } from "../login/page";

export default function AccountRecoveryPage() {
  const [error, setError] = useState("");
  const [token, setToken] = useState("");
  const [signInEmail, setSignInEmail] = useState("");
  const [manager, setManager] = useState("");

  async function claim(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const body = await apiJson<{ recovery_token: string }>("/api/v1/recovery/claim", {
        method: "POST",
        body: JSON.stringify({
          email: form.get("email"),
          password: form.get("password"),
          trc20_wallet: form.get("trc20_wallet"),
          next_of_kin_name: form.get("next_of_kin_name"),
          second_next_of_kin_name: form.get("second_next_of_kin_name"),
        }),
      });
      setToken(body.recovery_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Recovery could not be started");
    }
  }

  async function restore(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const body = await apiJson<{ sign_in_email: string; manager_name: string }>("/api/v1/recovery/restore", {
        method: "POST",
        body: JSON.stringify({ recovery_token: token, new_password: form.get("new_password") }),
      });
      setSignInEmail(body.sign_in_email);
      setManager(body.manager_name);
    } catch (err) {
      setError(err instanceof Error ? err.message : "The desk password could not be replaced");
    }
  }

  return (
    <AuthCard title="Recover the desk" error={error}>
      {signInEmail ? (
        <div className="text-sm">
          <p>{manager} can manage this desk.</p>
          <p className="mt-2">Sign in with <span className="num">{signInEmail}</span> and the new password. Two-factor sign-in was turned off for this recovery. Turn it on again from setup after you are in.</p>
          <Link className="inline-block mt-4" href="/login">Sign in</Link>
        </div>
      ) : token ? (
        <form className="flex flex-col gap-3" onSubmit={restore}>
          <p className="text-sm text-muted">Details matched. Choose the password the second next of kin will use to sign in. It replaces the current desk password and signs out other sessions.</p>
          <input name="new_password" type="password" placeholder="New desk password" autoComplete="new-password" required />
          <button className="primary" type="submit">Give management to the second next of kin</button>
        </form>
      ) : (
        <form className="flex flex-col gap-3" onSubmit={claim}>
          <p className="text-sm text-muted">Enter the recovery email, recovery password, TRC20 wallet, and both next-of-kin names saved on the desk.</p>
          <input name="email" type="email" placeholder="Recovery email" required />
          <input name="password" type="password" placeholder="Recovery password" required />
          <input name="trc20_wallet" placeholder="TRC20 wallet address" required />
          <input name="next_of_kin_name" placeholder="Next of kin full name" required />
          <input name="second_next_of_kin_name" placeholder="Second next of kin full name" required />
          <button className="primary" type="submit">Check recovery details</button>
        </form>
      )}
      <p className="text-sm text-muted mt-4"><Link href="/login">Back to sign in</Link></p>
    </AuthCard>
  );
}
