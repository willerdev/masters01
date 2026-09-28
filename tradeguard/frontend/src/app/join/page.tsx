"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { apiJson, saveSession } from "@/lib/api";

const MARKETS = ["fx", "indices", "commodities", "crypto"];

export default function JoinPage() {
  const router = useRouter();
  const [kind, setKind] = useState("investor");
  const [markets, setMarkets] = useState<string[]>(["fx"]);
  const [error, setError] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const answers = kind === "investor"
      ? {
          applicant_type: form.get("applicant_type"),
          country: form.get("country"),
          tax_residency: form.get("tax_residency"),
          date_of_birth: form.get("date_of_birth"),
          category: form.get("category"),
          source_of_funds: form.get("source_of_funds"),
          expected_amount: form.get("expected_amount"),
          horizon: form.get("horizon"),
          objective: form.get("objective"),
          experience: form.get("experience"),
          pep: form.get("pep"),
          phone: form.get("phone"),
          address: form.get("address"),
          id_type: form.get("id_type"),
          id_last4: form.get("id_last4"),
          risk_accepted: form.get("risk_accepted") === "on",
        }
      : {
          country: form.get("country"),
          phone: form.get("phone"),
          years_experience: Number(form.get("years_experience")),
          markets,
          style: form.get("style"),
          risk_per_trade_pct: form.get("risk_per_trade_pct"),
          daily_loss_pct: form.get("daily_loss_pct"),
          max_drawdown_pct: form.get("max_drawdown_pct"),
          max_positions: Number(form.get("max_positions")),
          track_record: form.get("track_record"),
          regulated: form.get("regulated"),
          license_number: form.get("license_number"),
          other_desks: form.get("other_desks"),
          excluded_symbols: form.get("excluded_symbols"),
          emergency_contact_name: form.get("emergency_contact_name"),
          emergency_contact_phone: form.get("emergency_contact_phone"),
          rules_accepted: form.get("rules_accepted") === "on",
        };
    try {
      const body = await apiJson<{ access_token: string }>("/api/v1/join", {
        method: "POST",
        body: JSON.stringify({
          code: form.get("code"),
          email: form.get("email"),
          password: form.get("password"),
          full_name: form.get("full_name"),
          kind,
          answers,
        }),
      });
      saveSession(body.access_token);
      router.push("/pending");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Application was not sent");
    }
  }

  return (
    <div className="min-h-screen grid place-items-center px-4 py-10">
      <div className="w-full max-w-2xl bg-panel border border-line rounded-lg p-6">
        <div className="text-xs tracking-[0.18em] text-muted">TRADEGUARD</div>
        <h1 className="text-2xl font-semibold mb-1">Apply to join</h1>
        <p className="text-sm text-muted mb-4">An admin reviews this before you can see a fund or a trading book. Use the join code they gave you.</p>
        {error ? <p className="text-loss text-sm mb-3">{error}</p> : null}
        <form className="grid md:grid-cols-2 gap-3" onSubmit={onSubmit}>
          <input name="code" placeholder="Join code" required className="uppercase" />
          <input name="full_name" placeholder="Legal name" required />
          <input name="email" type="email" placeholder="Email" required />
          <input name="password" type="password" placeholder="Password, 12+ characters" required />
          <label className="text-sm flex items-center gap-2">
            <input className="w-auto" type="radio" name="kind" checked={kind === "investor"} onChange={() => setKind("investor")} /> Investor
          </label>
          <label className="text-sm flex items-center gap-2">
            <input className="w-auto" type="radio" name="kind" checked={kind === "trader"} onChange={() => setKind("trader")} /> Trader
          </label>
          {kind === "investor" ? <InvestorFields /> : <TraderFields markets={markets} setMarkets={setMarkets} />}
          <button className="primary md:col-span-2" type="submit">Submit application</button>
        </form>
        <p className="text-sm text-muted mt-4"><Link href="/login">Already approved? Sign in</Link></p>
      </div>
    </div>
  );
}

function InvestorFields() {
  return (
    <>
      <select name="applicant_type" defaultValue="individual">
        <option value="individual">Individual</option>
        <option value="company">Company</option>
      </select>
      <select name="category" defaultValue="professional">
        <option value="retail">Retail</option>
        <option value="professional">Professional</option>
        <option value="accredited">Accredited</option>
      </select>
      <input name="country" placeholder="Country of residence" required />
      <input name="tax_residency" placeholder="Tax residency" required />
      <input name="date_of_birth" placeholder="Date of birth or incorporation YYYY-MM-DD" required />
      <input name="phone" placeholder="Phone" required />
      <input name="address" placeholder="Address" required className="md:col-span-2" />
      <select name="source_of_funds" defaultValue="business">
        <option value="salary">Salary</option>
        <option value="business">Business</option>
        <option value="investments">Investments</option>
        <option value="inheritance">Inheritance</option>
        <option value="other">Other</option>
      </select>
      <input name="expected_amount" type="number" min="1" step="0.01" placeholder="Amount you expect to commit" required />
      <select name="horizon" defaultValue="1_to_3y">
        <option value="under_1y">Horizon under 1 year</option>
        <option value="1_to_3y">Horizon 1 to 3 years</option>
        <option value="over_3y">Horizon over 3 years</option>
      </select>
      <select name="objective" defaultValue="growth">
        <option value="growth">Growth</option>
        <option value="income">Income</option>
        <option value="preservation">Capital preservation</option>
      </select>
      <select name="experience" defaultValue="some">
        <option value="none">No market experience</option>
        <option value="some">Some experience</option>
        <option value="extensive">Extensive experience</option>
      </select>
      <select name="pep" defaultValue="no">
        <option value="no">Not a politically exposed person</option>
        <option value="yes">Politically exposed person</option>
      </select>
      <select name="id_type" defaultValue="passport">
        <option value="passport">Passport</option>
        <option value="national_id">National ID</option>
        <option value="company_registration">Company registration</option>
      </select>
      <input name="id_last4" placeholder="Last 4 of that document" maxLength={4} required />
      <label className="text-sm flex gap-2 items-start md:col-span-2">
        <input className="w-auto mt-1" type="checkbox" name="risk_accepted" required />
        I understand the amount I commit can be lost, and a subscription is only recorded after the admin approves it.
      </label>
    </>
  );
}

function TraderFields({ markets, setMarkets }: { markets: string[]; setMarkets: (next: string[]) => void }) {
  return (
    <>
      <input name="country" placeholder="Country" required />
      <input name="phone" placeholder="Phone" required />
      <input name="years_experience" type="number" min="0" max="60" placeholder="Years trading" required />
      <select name="style" defaultValue="discretionary">
        <option value="discretionary">Discretionary</option>
        <option value="systematic">Systematic</option>
        <option value="mixed">Mixed</option>
      </select>
      <div className="md:col-span-2 flex flex-wrap gap-3 text-sm">
        {MARKETS.map((market) => (
          <label key={market} className="flex items-center gap-2">
            <input
              className="w-auto"
              type="checkbox"
              checked={markets.includes(market)}
              onChange={(event) => setMarkets(event.target.checked ? [...markets, market] : markets.filter((item) => item !== market))}
            />
            {market}
          </label>
        ))}
      </div>
      <input name="risk_per_trade_pct" type="number" min="0.01" step="0.01" placeholder="Risk per trade %" required />
      <input name="daily_loss_pct" type="number" min="0.01" step="0.01" placeholder="Daily loss %" required />
      <input name="max_drawdown_pct" type="number" min="0.01" step="0.01" placeholder="Max drawdown %" required />
      <input name="max_positions" type="number" min="1" max="50" placeholder="Max open positions" required />
      <select name="regulated" defaultValue="no">
        <option value="no">Not regulated</option>
        <option value="yes">Regulated</option>
      </select>
      <input name="license_number" placeholder="License number, if regulated" />
      <textarea name="track_record" placeholder="Describe your track record. Do not invent results." required className="md:col-span-2 min-h-24" />
      <input name="other_desks" placeholder="Other desks or prop firms" className="md:col-span-2" />
      <input name="excluded_symbols" placeholder="Symbols you will not trade" className="md:col-span-2" />
      <input name="emergency_contact_name" placeholder="Emergency contact name" required />
      <input name="emergency_contact_phone" placeholder="Emergency contact phone" required />
      <label className="text-sm flex gap-2 items-start md:col-span-2">
        <input className="w-auto mt-1" type="checkbox" name="rules_accepted" required />
        I will follow the desk risk rules. A block from the desk is final unless an admin pauses it.
      </label>
    </>
  );
}
