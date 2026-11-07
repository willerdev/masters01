"use client";

import { useState } from "react";

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

const NETWORKS: { id: string; label: string; placeholder: string; prefix: string }[] = [
  { id: "ethereum",  label: "Ethereum (ERC-20)",   placeholder: "0x…",        prefix: "0x" },
  { id: "bitcoin",   label: "Bitcoin (BTC)",        placeholder: "bc1… or 1…", prefix: ""   },
  { id: "tron",      label: "Tron (TRC-20)",        placeholder: "T…",         prefix: "T"  },
  { id: "bnb",       label: "BNB Smart Chain (BEP-20)", placeholder: "0x…",    prefix: "0x" },
  { id: "solana",    label: "Solana (SOL)",         placeholder: "…",          prefix: ""   },
  { id: "polygon",   label: "Polygon (MATIC)",      placeholder: "0x…",        prefix: "0x" },
  { id: "avalanche", label: "Avalanche (AVAX C-Chain)", placeholder: "0x…",    prefix: "0x" },
  { id: "litecoin",  label: "Litecoin (LTC)",       placeholder: "L… or M…",   prefix: ""   },
];

const STEPS = ["Personal Info", "Wallet Setup"];

type Step1 = { age: string; country: string; email: string };
type Step2 = { network: string; address: string };

function StepBar({ current, total }: { current: number; total: number }) {
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        {STEPS.map((label, i) => (
          <div key={i} className="flex items-center gap-2 flex-1 last:flex-none">
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
        Step {current + 1} of {total}
      </p>
    </div>
  );
}

function Step1Form({
  data,
  onChange,
}: {
  data: Step1;
  onChange: (d: Step1) => void;
}) {
  const set = (key: keyof Step1) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    onChange({ ...data, [key]: e.target.value });

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold m-0">Tell us about yourself</h2>
      <p className="text-sm" style={{ color: "var(--muted)", marginTop: -8 }}>
        We use this information to personalise your experience.
      </p>

      <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
        Age
        <input
          type="number"
          min={18}
          max={120}
          placeholder="e.g. 28"
          value={data.age}
          onChange={set("age")}
          required
        />
        {data.age && parseInt(data.age) < 18 && (
          <span className="text-xs" style={{ color: "var(--loss)" }}>
            You must be at least 18 years old.
          </span>
        )}
      </label>

      <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
        Country
        <select value={data.country} onChange={set("country")} required>
          <option value="" disabled>Select your country</option>
          {COUNTRIES.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>

      <label className="text-sm flex flex-col gap-1" style={{ color: "var(--muted)" }}>
        Email address
        <input
          type="email"
          placeholder="you@example.com"
          value={data.email}
          onChange={set("email")}
          required
        />
      </label>
    </div>
  );
}

function Step2Form({
  data,
  onChange,
}: {
  data: Step2;
  onChange: (d: Step2) => void;
}) {
  const selectedNet = NETWORKS.find((n) => n.id === data.network);

  function onNetwork(id: string) {
    onChange({ network: id, address: "" });
  }

  function onAddress(e: React.ChangeEvent<HTMLInputElement>) {
    onChange({ ...data, address: e.target.value });
  }

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold m-0">Set up your wallet</h2>
      <p className="text-sm" style={{ color: "var(--muted)", marginTop: -8 }}>
        Choose a network and enter the wallet address you want to use.
      </p>

      <div>
        <p className="text-xs font-medium mb-2" style={{ color: "var(--muted)", letterSpacing: "0.06em", textTransform: "uppercase" }}>
          Network
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {NETWORKS.map((net) => (
            <label
              key={net.id}
              className={`choice${data.network === net.id ? " on" : ""}`}
              style={{ cursor: "pointer" }}
            >
              <input
                type="radio"
                name="network"
                value={net.id}
                checked={data.network === net.id}
                onChange={() => onNetwork(net.id)}
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
              onChange={onAddress}
              required
              autoComplete="off"
              spellCheck={false}
              style={{ fontFamily: "var(--font-mono, monospace)", paddingRight: data.address ? "2.5rem" : undefined }}
            />
            {data.address && (
              <button
                type="button"
                onClick={() => onChange({ ...data, address: "" })}
                style={{
                  position: "absolute",
                  right: 8,
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "transparent",
                  border: "none",
                  color: "var(--muted)",
                  cursor: "pointer",
                  padding: "0 4px",
                  width: "auto",
                  fontSize: 14,
                }}
                aria-label="Clear address"
              >
                ✕
              </button>
            )}
          </div>
          <span className="text-xs" style={{ color: "var(--muted)" }}>
            Double-check this address. Funds sent to the wrong address cannot be recovered.
          </span>
        </label>
      )}
    </div>
  );
}

function ReviewCard({ step1, step2 }: { step1: Step1; step2: Step2 }) {
  const net = NETWORKS.find((n) => n.id === step2.network);
  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold m-0">All done!</h2>
      <p className="text-sm" style={{ color: "var(--muted)", marginTop: -8 }}>
        Your onboarding profile has been saved. You can update these details from your account settings.
      </p>
      <fieldset className="section">
        <legend>Personal Info</legend>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm mt-1">
          <dt style={{ color: "var(--muted)" }}>Age</dt>
          <dd className="m-0">{step1.age}</dd>
          <dt style={{ color: "var(--muted)" }}>Country</dt>
          <dd className="m-0">{step1.country}</dd>
          <dt style={{ color: "var(--muted)" }}>Email</dt>
          <dd className="m-0 break-all">{step1.email}</dd>
        </dl>
      </fieldset>
      <fieldset className="section">
        <legend>Wallet</legend>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm mt-1">
          <dt style={{ color: "var(--muted)" }}>Network</dt>
          <dd className="m-0">{net?.label ?? step2.network}</dd>
          <dt style={{ color: "var(--muted)" }}>Address</dt>
          <dd className="m-0 num break-all text-xs">{step2.address}</dd>
        </dl>
      </fieldset>
    </div>
  );
}

export default function OnboardingPage() {
  const [step, setStep] = useState(0);
  const [submitted, setSubmitted] = useState(false);

  const [step1, setStep1] = useState<Step1>({ age: "", country: "", email: "" });
  const [step2, setStep2] = useState<Step2>({ network: "", address: "" });

  const [error, setError] = useState("");

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

  function onNext(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (step === 0) {
      if (!step1Valid()) {
        setError("Please fill in all fields correctly before continuing.");
        return;
      }
      setStep(1);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (!step2Valid()) {
      setError("Please choose a network and enter your wallet address.");
      return;
    }
    setSubmitted(true);
  }

  function onBack() {
    setError("");
    setStep((s) => Math.max(0, s - 1));
  }

  if (submitted) {
    return (
      <div className="min-h-screen grid place-items-center px-4">
        <div className="w-full max-w-xl bg-panel border border-line rounded-lg p-6">
          <div className="text-xs tracking-widest mb-4" style={{ color: "var(--muted)" }}>TRADEGUARD</div>
          <ReviewCard step1={step1} step2={step2} />
          <div className="mt-6 flex gap-3">
            <a href="/dashboard" className="primary" style={{ display: "inline-block", borderRadius: 6, padding: "8px 18px", background: "var(--accent)", color: "var(--on-accent)", fontWeight: 600, textDecoration: "none" }}>
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
    <div className="min-h-screen grid place-items-center px-4">
      <div className="w-full max-w-xl bg-panel border border-line rounded-lg p-6">
        <div className="text-xs tracking-widest mb-4" style={{ color: "var(--muted)", letterSpacing: "0.18em" }}>
          TRADEGUARD
        </div>

        <StepBar current={step} total={STEPS.length} />

        {error && (
          <p className="text-sm mb-4" style={{ color: "var(--loss)" }}>{error}</p>
        )}

        {step === 0 && (
          <form onSubmit={onNext} noValidate>
            <Step1Form data={step1} onChange={setStep1} />
            <div className="flex justify-end mt-6">
              <button className="primary" type="submit">
                Next →
              </button>
            </div>
          </form>
        )}

        {step === 1 && (
          <form onSubmit={onSubmit} noValidate>
            <Step2Form data={step2} onChange={setStep2} />
            <div className="flex justify-between mt-6">
              <button type="button" className="ghost" onClick={onBack}>
                ← Previous
              </button>
              <button className="primary" type="submit" disabled={!step2Valid()}>
                Finish setup
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
