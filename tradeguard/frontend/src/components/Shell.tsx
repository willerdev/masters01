"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, apiJson, clearSession, type User } from "@/lib/api";

const MENUS: { label: string; items: [string, string, IconName][] }[] = [
  { label: "Dashboard", items: [["/dashboard", "Dashboard", "grid"]] },
  {
    label: "Trading",
    items: [
      ["/accounts", "Accounts", "wallet"],
      ["/positions", "Positions", "layers"],
      ["/trades", "Trades", "swap"],
      ["/journal", "Journal", "book"],
    ],
  },
  {
    label: "Risk",
    items: [
      ["/risk-engine", "Risk Engine", "shield"],
      ["/risk-rules", "Risk Rules", "sliders"],
    ],
  },
  { label: "Funds", items: [["/funds", "Funds", "fund"]] },
  { label: "Assets", items: [["/assets", "Assets", "coin"]] },
  { label: "Alerts", items: [["/alerts", "Alerts", "bell"]] },
  {
    label: "Reports",
    items: [
      ["/analytics", "Analytics", "chart"],
      ["/reports", "Reports", "file"],
    ],
  },
  {
    label: "Connect",
    items: [
      ["/webhooks", "Webhooks", "link"],
      ["/api-keys", "API Keys", "key"],
      ["/payments", "Payments", "card"],
      ["/telegram", "Telegram", "send"],
    ],
  },
  {
    label: "System",
    items: [
      ["/settings", "Settings", "gear"],
      ["/recovery", "Recovery", "lock"],
      ["/audit", "Audit Logs", "list"],
      ["/applications", "Applications", "users"],
    ],
  },
];

const LINKS = MENUS.flatMap((menu) => menu.items);
const DESK_ROLES = ["SUPER_ADMIN", "ADMIN", "RISK_MANAGER", "TRADER", "VIEWER"];

export function homeFor(roles: string[]) {
  if (roles.some((role) => DESK_ROLES.includes(role))) return "/dashboard";
  if (roles.includes("INVESTOR")) return "/investor";
  if (roles.includes("PORTAL_TRADER")) return "/trader";
  return "/pending";
}

type IconName = "grid" | "wallet" | "layers" | "swap" | "book" | "shield" | "sliders" | "bell" | "chart" | "file" | "link" | "key" | "card" | "send" | "gear" | "lock" | "list" | "fund" | "users" | "coin";

function Icon({ name }: { name: IconName }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      {name === "grid" ? <path {...common} d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" /> : null}
      {name === "wallet" ? <path {...common} d="M3 8h18v11H3zM3 8l2-3h12l2 3M16 13h3" /> : null}
      {name === "layers" ? <path {...common} d="M12 3l9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 16l9 5 9-5" /> : null}
      {name === "swap" ? <path {...common} d="M7 7h11l-3-3M17 17H6l3 3" /> : null}
      {name === "book" ? <path {...common} d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3 3zM5 4v16" /> : null}
      {name === "shield" ? <path {...common} d="M12 3l8 3v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6z" /> : null}
      {name === "sliders" ? <path {...common} d="M4 7h16M4 17h16M8 7v4M16 13v4" /> : null}
      {name === "bell" ? <path {...common} d="M6 16V10a6 6 0 1 1 12 0v6l2 2H4zM10 20a2 2 0 0 0 4 0" /> : null}
      {name === "chart" ? <path {...common} d="M4 19V5M4 19h16M8 15l4-5 3 3 5-7" /> : null}
      {name === "file" ? <path {...common} d="M7 3h7l5 5v13H7zM14 3v5h5" /> : null}
      {name === "link" ? <path {...common} d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" /> : null}
      {name === "key" ? <path {...common} d="M8 15a4 4 0 1 1 3-6l9 3v3h-3v2h-3l-2-2" /> : null}
      {name === "card" ? <path {...common} d="M3 7h18v11H3zM3 11h18" /> : null}
      {name === "send" ? <path {...common} d="M4 12l16-7-6 16-3-6z" /> : null}
      {name === "gear" ? <path {...common} d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.5 1.5M16.9 16.9l1.5 1.5M18.4 5.6l-1.5 1.5M7.1 16.9l-1.5 1.5" /> : null}
      {name === "lock" ? <path {...common} d="M8 11V8a4 4 0 0 1 8 0v3M6 11h12v9H6z" /> : null}
      {name === "list" ? <path {...common} d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" /> : null}
      {name === "users" ? <path {...common} d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M9.5 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6M20 21v-2a3.5 3.5 0 0 0-2.5-3.3M16.5 5.1a3 3 0 0 1 0 5.6" /> : null}
      {name === "fund" ? <path {...common} d="M4 20V10l8-6 8 6v10H4zM9 20v-6h6v6" /> : null}
      {name === "coin" ? <path {...common} d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9 12h6" /> : null}
    </svg>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [theme, setTheme] = useState("light");
  const [ready, setReady] = useState(false);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const menuRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const stored = localStorage.getItem("tg-theme") || "light";
    setTheme(stored);
    document.documentElement.dataset.theme = stored;
    let cancelled = false;
    api("/api/v1/auth/me")
      .then(async (response) => {
        if (!response.ok) {
          router.replace("/login");
          return;
        }
        const me = await response.json();
        if (cancelled) return;
        setUser(me);
        const home = homeFor(me.roles || []);
        if (home !== "/dashboard") {
          router.replace(home);
          return;
        }
        if (pathname !== "/setup") {
          const setup = await apiJson<{ complete: boolean }>("/api/v1/setup/status");
          if (!setup.complete) {
            router.replace("/setup");
            return;
          }
        }
        setReady(true);
      })
      .catch(() => router.replace("/login"));
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  useEffect(() => {
    setOpenMenu(null);
  }, [pathname]);

  useEffect(() => {
    function close(event: MouseEvent) {
      if (!menuRef.current?.contains(event.target as Node)) setOpenMenu(null);
    }
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  function toggleTheme() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem("tg-theme", next);
    document.documentElement.dataset.theme = next;
  }

  async function logout() {
    await api("/api/v1/auth/logout", { method: "POST" });
    clearSession();
    router.replace("/login");
  }

  if (!ready) {
    return <div className="min-h-screen grid place-items-center text-muted">Loading desk…</div>;
  }

  return (
    <div className="desk-shell">
      <aside className="desk-rail">
        <Link href="/dashboard" className="desk-mark" title="TradeGuard">TG</Link>
        <nav className="flex flex-col items-stretch gap-1" onMouseDown={(event) => event.stopPropagation()}>
          {LINKS.map(([href, label, icon]) => {
            const on = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link key={href} href={href} className={on ? "on" : ""} title={label} aria-label={label}>
                <Icon name={icon} />
                <span>{label}</span>
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="desk-main">
        <header className="desk-top">
          <nav className="desk-menu" ref={menuRef}>
            {MENUS.map((menu) => {
              const active = menu.items.some(([href]) => pathname === href || pathname.startsWith(`${href}/`));
              if (menu.items.length === 1) {
                const [href, label] = menu.items[0];
                return <Link key={label} href={href} className={active ? "on" : ""}>{label}</Link>;
              }
              const open = openMenu === menu.label;
              return (
                <div key={menu.label} className="desk-drop">
                  <button
                    type="button"
                    className={active ? "menu on" : "menu"}
                    aria-expanded={open}
                    onClick={() => setOpenMenu(open ? null : menu.label)}
                  >
                    {menu.label}
                  </button>
                  {open ? (
                    <div className="desk-sub">
                      {menu.items.map(([href, label]) => {
                        const on = pathname === href || pathname.startsWith(`${href}/`);
                        return <Link key={href} href={href} className={on ? "on" : ""}>{label}</Link>;
                      })}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </nav>
          <div className="desk-user">
            <span>{user?.email}</span>
            <button className="ghost" onClick={toggleTheme}>{theme === "dark" ? "Light" : "Dark"}</button>
            <button className="ghost" onClick={logout}>Log out</button>
          </div>
        </header>
        <main className="desk-content">{children}</main>
      </div>
    </div>
  );
}

export function PageTitle({ title, detail }: { title: string; detail?: string }) {
  return (
    <header className="mb-5">
      <h1 className="text-2xl font-semibold">{title}</h1>
      {detail ? <p className="text-sm text-muted mt-1">{detail}</p> : null}
    </header>
  );
}
