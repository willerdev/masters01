"use client";

import { useState } from "react";
import { apiJson } from "@/lib/api";

// ─── Static data ────────────────────────────────────────────────────────────

const COUNTRIES = [
  "Afghanistan","Albania","Algeria","Andorra","Angola","Antigua and Barbuda","Argentina","Armenia","Australia",
  "Austria","Azerbaijan","Bahamas","Bahrain","Bangladesh","Barbados","Belarus","Belgium","Belize","Benin",
  "Bhutan","Bolivia","Bosnia and Herzegovina","Botswana","Brazil","Brunei","Bulgaria","Burkina Faso","Burundi",
  "Cabo Verde","Cambodia","Cameroon","Canada","Central African Republic","Chad","Chile","China","Colombia",
  "Comoros","Congo (Brazzaville)","Congo (Kinshasa)","Costa Rica","Croatia","Cuba","Cyprus","Czech Republic",
  "Denmark","Djibouti","Dominica","Dominican Republic","Ecuador","Egypt","El Salvador","Equatorial Guinea",
  "Eritrea","Estonia","Eswatini","Ethiopia","Fiji","Finland","France","Gabon","Gambia","Georgia","Germany",
  "Ghana","Greece","Grenada","Guatemala","Guinea","Guinea-Bissau","Guyana","Haiti","Honduras","Hungary",
  "Iceland","India","Indonesia","Iran","Iraq","Ireland","Israel","Italy","Jamaica","Japan","Jordan","Kazakhstan",
  "Kenya","Kiribati","Kuwait","Kyrgyzstan","Laos","Latvia","Lebanon","Lesotho","Liberia","Libya","Liechtenstein",
  "Lithuania","Luxembourg","Madagascar","Malawi","Malaysia","Maldives","Mali","Malta","Marshall Islands",
  "Mauritania","Mauritius","Mexico","Micronesia","Moldova","Monaco","Mongolia","Montenegro","Morocco","Mozambique",
  "Myanmar","Namibia","Nauru","Nepal","Netherlands","New Zealand","Nicaragua","Niger","Nigeria","North Korea",
  "North Macedonia","Norway","Oman","Pakistan","Palau","Panama","Papua New Guinea","Paraguay","Peru","Philippines",
  "Poland","Portugal","Qatar","Romania","Russia","Rwanda","Saint Kitts and Nevis","Saint Lucia",
  "Saint Vincent and the Grenadines","Samoa","San Marino","Saudi Arabia","Senegal","Serbia","Seychelles",
  "Sierra Leone","Singapore","Slovakia","Slovenia","Solomon Islands","Somalia","South Africa","South Korea",
  "South Sudan","Spain","Sri Lanka","Sudan","Suriname","Sweden","Switzerland","Syria","Taiwan","Tajikistan",
  "Tanzania","Thailand","Timor-Leste","Togo","Tonga","Trinidad and Tobago","Tunisia","Turkey","Turkmenistan",
  "Tuvalu","Uganda","Ukraine","United Arab Emirates","United Kingdom","United States","Uruguay","Uzbekistan",
  "Vanuatu","Vatican City","Venezuela","Vietnam","Yemen","Zambia","Zimbabwe",
];

const NETWORKS = [
  { id: "ethereum",  label: "Ethereum (ERC-20)",        placeholder: "0x…" },
  { id: "bitcoin",   label: "Bitcoin (BTC)",             placeholder: "bc1… or 1…" },
  { id: "tron",      label: "Tron (TRC-20)",             placeholder: "T…" },
  { id: "bnb",       label: "BNB Smart Chain (BEP-20)",  placeholder: "0x…" },
  { id: "solana",    label: "Solana (SOL)",              placeholder: "…" },
  { id: "polygon",   label: "Polygon (MATIC)",           placeholder: "0x…" },
  { id: "avalanche", label: "Avalanche (AVAX C-Chain)",  placeholder: "0x…" },
  { id: "litecoin",  label: "Litecoin (LTC)",            placeholder: "L… or M…" },
];

type RiskBadge = "zero" | "low" | "medium" | "high" | "potential";

interface Activity {
  id: string;
  label: string;
  description: string;
  risk: RiskBadge;
  riskLabel: string;
  detail?: string;
}

const ACTIVITIES: Activity[] = [
  {
    id: "forex_trading",
    label: "Forex Trading",
    description: "Trade major, minor, and exotic currency pairs on global foreign exchange markets.",
    risk: "high",
    riskLabel: "Risky",
  },
  {
    id: "mining",
    label: "Mining",
    description: "Earn rewards by contributing computational power to validate blockchain transactions.",
    risk: "medium",
    riskLabel: "Medium risk",
  },
  {
    id: "contracts",
    label: "Contracts",
    description: "Fixed-term yield contracts with guaranteed returns.",
    risk: "zero",
    riskLabel: "0 Risk",
    detail: "30 – 50% ROI weekly",
  },
  {
    id: "futures_trading",
    label: "Futures Trading",
    description: "Buy and sell futures contracts on commodities, indices, and crypto.",
    risk: "potential",
    riskLabel: "Potential losses",
  },
  {
    id: "propfirms",
    label: "Prop Firms",
    description: "Trade with a proprietary firm's capital after passing an evaluation challenge.",
    risk: "medium",
    riskLabel: "Medium risk",
  },
  {
    id: "trading_indices",
    label: "Trading Indices",
    description: "Speculate on the price movement of stock market indices and synthetic instruments.",
    risk: "medium",
    riskLabel: "Medium risk",
  },
  {
    id: "investment",
    label: "Investment",
    description: "Managed portfolio investment with consistent daily returns.",
    risk: "low",
    riskLabel: "Low risk",
    detail: "2% daily return",
  },
  {
    id: "liquidity_pools",
    label: "Liquidity Pools",
    description: "Provide liquidity to DeFi protocols and earn a share of trading fees.",
    risk: "zero",
    riskLabel: "0 Risk",
  },
];

const INDICES_BROKERS = [
  { id: "weltrade", label: "Weltrade" },
  { id: "deriv",    label: "Deriv" },
  { id: "spredix",  label: "Spredix" },
];

const RISK_STYLE: Record<RiskBadge, { color: string; bg: string }> = {
  zero:      { color: "var(--profit)",  bg: "color-mix(in srgb, var(--profit) 14%, transparent)" },
  low:       { color: "var(--profit)",  bg: "color-mix(in srgb, var(--profit) 10%, transparent)" },
  medium:    { color: "var(--warn)",    bg: "color-mix(in srgb, var(--warn) 16%, transparent)" },
  high:      { color: "var(--loss)",    bg: "color-mix(in srgb, var(--loss) 14%, transparent)" },
  potential: { color: "var(--loss)",    bg: "color-mix(in srgb, var(--loss) 10%, transparent)" },
};

const STEPS = ["Personal Info", "Wallet Setup", "Activities"];

// ─── Types ───────────────────────────────────────────────────────────────────

type Step1 = { age: string; country: string; email: string };
type Step2 = { network: string; address: string };
type Step3 = { activities: string[]; indicesBroker: string };

// ─── Step progress bar ───────────────────────────────────────────────────────

function StepBar({ current }: { current: number }) {
  return (
    <div className="mb-6">
      <div className="flex items-center gap-1 mb-3">
        {STEPS.map((label, i) => (
          <div key={i} className="flex items-center gap-1 flex-1 last:flex-none">
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-none"
              style={{
                background: i < current ? "var(--profit)" : i === current ? "var(--accent)" : "var(--panel-2)",
                color: i <= current ? "var(--on-accent)" : "var(--muted)",
                border: i > current ? "1px solid var(--line)" : "none",
              }}
            >
              {i < current ? "✓" : i + 1}
            </div>
            <span
              className="text-xs font-medium whitespace-nowrap"
              style={{ color: i === current ? "var(--ink)" : "var(--muted)" }}
            >
              {label}
            </span>
            {i < STEPS.length - 1 && (
              <div
                className="flex-1 h-px"
                style={{ background: i < current ? "var(--profit)" : "var(--line)" }}
              />
            )}
          </div>
        ))}
      </div>
      <p className="text-xs" style={{ color: "var(--muted)" }}>
        Step {current + 1} of {STEPS.length}
      </p>
    </div>
  );
}

// ─── Step 1 ──────────────────────────────────────────────────────────────────

function Step1Form({ data, onChange }: { data: Step1; onChange: (d: Step1) => void }) {
  const set = (key: keyof Step1) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      onChange({ ...data, [key]: e.target.value });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold m-0">Tell us about yourself</h2>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          We use this to personalise your experience and keep your account secure.
        </p>
      </div>

      <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
        Age
        <input type="number" min={18} max={120} placeholder="e.g. 28" value={data.age} onChange={set("age")} required />
        {data.age !== "" && parseInt(data.age) < 18 && (
          <span className="text-xs" style={{ color: "var(--loss)" }}>You must be at least 18 years old.</span>
        )}
      </label>

      <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
        Country
        <select value={data.country} onChange={set("country")} required>
          <option value="" disabled>Select your country</option>
          {COUNTRIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>

      <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
        Email address
        <input type="email" placeholder="you@example.com" value={data.email} onChange={set("email")} required />
      </label>
    </div>
  );
}

// ─── Step 2 ──────────────────────────────────────────────────────────────────

function Step2Form({ data, onChange }: { data: Step2; onChange: (d: Step2) => void }) {
  const selectedNet = NETWORKS.find((n) => n.id === data.network);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold m-0">Set up your wallet</h2>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          Choose a network and enter the wallet address you want to use.
        </p>
      </div>

      <div>
        <p className="text-xs font-medium mb-2" style={{ color: "var(--muted)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
          Network
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {NETWORKS.map((net) => (
            <label key={net.id} className={`choice${data.network === net.id ? " on" : ""}`} style={{ cursor: "pointer" }}>
              <input
                type="radio" name="network" value={net.id}
                checked={data.network === net.id}
                onChange={() => onChange({ network: net.id, address: "" })}
                required
              />
              <span className="text-sm font-medium">{net.label}</span>
            </label>
          ))}
        </div>
      </div>

      {selectedNet && (
        <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
          Wallet address
          <div style={{ position: "relative" }}>
            <input
              type="text"
              placeholder={selectedNet.placeholder}
              value={data.address}
              onChange={(e) => onChange({ ...data, address: e.target.value })}
              required autoComplete="off" spellCheck={false}
              style={{ fontFamily: "monospace", paddingRight: data.address ? "2.5rem" : undefined }}
            />
            {data.address && (
              <button
                type="button"
                onClick={() => onChange({ ...data, address: "" })}
                style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "transparent", border: "none", color: "var(--muted)", cursor: "pointer", padding: "0 4px", width: "auto", fontSize: 14 }}
                aria-label="Clear"
              >✕</button>
            )}
          </div>
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            Double-check this address — funds sent to the wrong address cannot be recovered.
          </span>
        </label>
      )}
    </div>
  );
}

// ─── Step 3 ──────────────────────────────────────────────────────────────────

function ActivityCard({
  activity,
  selected,
  onToggle,
}: {
  activity: Activity;
  selected: boolean;
  onToggle: () => void;
}) {
  const riskStyle = RISK_STYLE[activity.risk];
  return (
    <button
      type="button"
      onClick={onToggle}
      style={{
        textAlign: "left",
        border: `1px solid ${selected ? "var(--accent)" : "var(--line)"}`,
        borderRadius: 8,
        padding: "12px 14px",
        background: selected ? "color-mix(in srgb, var(--accent) 8%, var(--panel))" : "var(--panel)",
        cursor: "pointer",
        width: "100%",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        transition: "border-color 0.12s, background 0.12s",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>{activity.label}</span>
        <span
          className="pill"
          style={{ color: riskStyle.color, background: riskStyle.bg, flexShrink: 0 }}
        >
          {activity.riskLabel}
        </span>
      </div>
      <p style={{ margin: 0, fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
        {activity.description}
      </p>
      {activity.detail && (
        <span style={{ fontSize: 11, fontWeight: 700, color: riskStyle.color, letterSpacing: "0.04em" }}>
          {activity.detail}
        </span>
      )}
    </button>
  );
}

function Step3Form({ data, onChange }: { data: Step3; onChange: (d: Step3) => void }) {
  const needsBroker = data.activities.includes("trading_indices");

  function toggleActivity(id: string) {
    const next = data.activities.includes(id)
      ? data.activities.filter((a) => a !== id)
      : [...data.activities, id];
    onChange({ ...data, activities: next, indicesBroker: next.includes("trading_indices") ? data.indicesBroker : "" });
  }

  function onBroker(id: string) {
    onChange({ ...data, indicesBroker: id });
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold m-0">Choose your activities</h2>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          Select everything you plan to do — you can pick multiple. You can change these later.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {ACTIVITIES.map((act) => (
          <ActivityCard
            key={act.id}
            activity={act}
            selected={data.activities.includes(act.id)}
            onToggle={() => toggleActivity(act.id)}
          />
        ))}
      </div>

      {needsBroker && (
        <div>
          <p className="text-xs font-medium mb-2" style={{ color: "var(--muted)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
            Indices broker
          </p>
          <div className="grid grid-cols-3 gap-2">
            {INDICES_BROKERS.map((b) => (
              <label
                key={b.id}
                className={`choice${data.indicesBroker === b.id ? " on" : ""}`}
                style={{ cursor: "pointer", justifyContent: "center" }}
              >
                <input
                  type="radio" name="indices_broker" value={b.id}
                  checked={data.indicesBroker === b.id}
                  onChange={() => onBroker(b.id)}
                  required
                />
                <span className="text-sm font-medium">{b.label}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {data.activities.length === 0 && (
        <p className="text-xs" style={{ color: "var(--loss)" }}>
          Select at least one activity to continue.
        </p>
      )}
    </div>
  );
}

// ─── Review card ─────────────────────────────────────────────────────────────

function ReviewCard({ step1, step2, step3 }: { step1: Step1; step2: Step2; step3: Step3 }) {
  const net = NETWORKS.find((n) => n.id === step2.network);
  const broker = INDICES_BROKERS.find((b) => b.id === step3.indicesBroker);
  const activityLabels = step3.activities.map(
    (id) => ACTIVITIES.find((a) => a.id === id)?.label ?? id
  );

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-semibold m-0">You're all set!</h2>
        <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
          Your profile has been saved. You can update these details from your account settings at any time.
        </p>
      </div>

      <fieldset className="section">
        <legend>Personal Info</legend>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm mt-1">
          <dt style={{ color: "var(--muted)" }}>Age</dt>     <dd className="m-0">{step1.age}</dd>
          <dt style={{ color: "var(--muted)" }}>Country</dt> <dd className="m-0">{step1.country}</dd>
          <dt style={{ color: "var(--muted)" }}>Email</dt>   <dd className="m-0 break-all">{step1.email}</dd>
        </dl>
      </fieldset>

      <fieldset className="section">
        <legend>Wallet</legend>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm mt-1">
          <dt style={{ color: "var(--muted)" }}>Network</dt> <dd className="m-0">{net?.label ?? step2.network}</dd>
          <dt style={{ color: "var(--muted)" }}>Address</dt>
          <dd className="m-0 num break-all text-xs">{step2.address}</dd>
        </dl>
      </fieldset>

      <fieldset className="section">
        <legend>Activities</legend>
        <div className="flex flex-wrap gap-2 mt-1">
          {activityLabels.map((label) => (
            <span key={label} className="pill idle">{label}</span>
          ))}
        </div>
        {broker && (
          <p className="text-xs mt-3" style={{ color: "var(--muted)" }}>
            Indices broker: <strong style={{ color: "var(--ink)" }}>{broker.label}</strong>
          </p>
        )}
      </fieldset>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function OnboardingPage() {
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");

  const [step1, setStep1] = useState<Step1>({ age: "", country: "", email: "" });
  const [step2, setStep2] = useState<Step2>({ network: "", address: "" });
  const [step3, setStep3] = useState<Step3>({ activities: [], indicesBroker: "" });

  function step1Valid() {
    return (
      step1.age !== "" &&
      parseInt(step1.age) >= 18 &&
      step1.country !== "" &&
      /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(step1.email)
    );
  }

  function step2Valid() {
    return step2.network !== "" && step2.address.trim().length >= 10;
  }

  function step3Valid() {
    if (step3.activities.length === 0) return false;
    if (step3.activities.includes("trading_indices") && !step3.indicesBroker) return false;
    return true;
  }

  function onNext(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (step === 0 && !step1Valid()) {
      setError("Please fill in all fields correctly before continuing.");
      return;
    }
    setStep((s) => s + 1);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!step3Valid()) {
      setError(
        step3.activities.includes("trading_indices") && !step3.indicesBroker
          ? "Please choose a broker for Trading Indices."
          : "Select at least one activity to continue."
      );
      return;
    }

    setSaving(true);
    try {
      await apiJson("/api/v1/onboarding", {
        method: "POST",
        body: JSON.stringify({
          email: step1.email,
          age: parseInt(step1.age),
          country: step1.country,
          wallet_network: step2.network,
          wallet_address: step2.address,
          activities: step3.activities,
          indices_broker: step3.indicesBroker,
        }),
      });
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save your profile. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  function onBack() {
    setError("");
    setStep((s) => Math.max(0, s - 1));
  }

  if (submitted) {
    return (
      <div className="min-h-screen grid place-items-center px-4">
        <div className="w-full max-w-2xl bg-panel border border-line rounded-lg p-6">
          <div className="text-xs tracking-widest mb-4" style={{ color: "var(--muted)", letterSpacing: "0.18em" }}>TRADEGUARD</div>
          <ReviewCard step1={step1} step2={step2} step3={step3} />
          <div className="mt-6 flex gap-3 flex-wrap">
            <a
              href="/dashboard"
              style={{ display: "inline-block", borderRadius: 6, padding: "8px 18px", background: "var(--accent)", color: "var(--on-accent)", fontWeight: 600, textDecoration: "none" }}
            >
              Go to dashboard
            </a>
            <button className="ghost" onClick={() => { setSubmitted(false); setStep(0); }}>
              Start over
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen grid place-items-center px-4 py-8">
      <div className="w-full max-w-2xl bg-panel border border-line rounded-lg p-6">
        <div className="text-xs tracking-widest mb-4" style={{ color: "var(--muted)", letterSpacing: "0.18em" }}>TRADEGUARD</div>

        <StepBar current={step} />

        {error && <p className="text-sm mb-4" style={{ color: "var(--loss)" }}>{error}</p>}

        {step === 0 && (
          <form onSubmit={onNext} noValidate>
            <Step1Form data={step1} onChange={setStep1} />
            <div className="flex justify-end mt-6">
              <button className="primary" type="submit">Next →</button>
            </div>
          </form>
        )}

        {step === 1 && (
          <form onSubmit={onNext} noValidate>
            <Step2Form data={step2} onChange={setStep2} />
            <div className="flex justify-between mt-6">
              <button type="button" className="ghost" onClick={onBack}>← Previous</button>
              <button className="primary" type="submit" disabled={!step2Valid()}>Next →</button>
            </div>
          </form>
        )}

        {step === 2 && (
          <form onSubmit={onSubmit} noValidate>
            <Step3Form data={step3} onChange={setStep3} />
            <div className="flex justify-between mt-6">
              <button type="button" className="ghost" onClick={onBack}>← Previous</button>
              <button className="primary" type="submit" disabled={!step3Valid() || saving}>
                {saving ? "Saving…" : "Finish setup"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
