"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Bell, Briefcase, CheckCircle2, FileText, History, LayoutDashboard, Menu, Plug, ScrollText, Search, Settings, Shield, User, X, Zap } from "lucide-react";
import { api, fmtDate, token, useApi } from "@/lib/api";
import { cx, Loading } from "@/components/ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/profile", label: "My Profile", icon: User },
  { href: "/resumes", label: "Resume Manager", icon: FileText },
  { href: "/preferences", label: "Job Search Preferences", icon: Search },
  { href: "/jobs", label: "Discovered Jobs", icon: Briefcase },
  { href: "/ready", label: "Ready to Apply", icon: CheckCircle2 },
  { href: "/history", label: "Application History", icon: History },
  { href: "/reports", label: "Daily Reports", icon: ScrollText },
  { href: "/automation", label: "Automation Settings", icon: Zap },
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/settings", label: "Settings and Privacy", icon: Shield },
];

function Bell_() {
  const [open, setOpen] = useState(false);
  const { data, reload } = useApi<any[]>("/api/notifications?limit=20");
  const unread = (data || []).filter((n) => !n.read_at).length;
  return (
    <div className="relative">
      <button aria-label={`Notifications (${unread} unread)`} onClick={() => { setOpen(!open); reload(); }} className="relative rounded-lg p-2 text-slate-600 hover:bg-slate-100">
        <Bell className="h-5 w-5" />
        {unread > 0 && <span className="absolute right-1 top-1 h-2.5 w-2.5 rounded-full bg-red-500" />}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 max-h-96 w-80 overflow-auto rounded-xl border border-slate-200 bg-white shadow-lg">
          {(data || []).length === 0 && <p className="p-4 text-sm text-slate-500">No notifications yet.</p>}
          {(data || []).map((n) => (
            <button key={n.id} onClick={async () => { await api(`/api/notifications/${n.id}/read`, { method: "POST" }); reload(); }}
              className={cx("block w-full border-b border-slate-100 px-4 py-3 text-left hover:bg-slate-50", !n.read_at && "bg-brand-50")}>
              <div className="text-xs uppercase tracking-wide text-slate-400">{n.notification_type.replace(/_/g, " ")} · {fmtDate(n.created_at)}</div>
              <div className="text-sm font-medium text-slate-800">{n.title}</div>
              {n.content && <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{n.content}</div>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [ready, setReady] = useState(false);
  const [menu, setMenu] = useState(false);
  const { data: me } = useApi<any>(ready ? "/api/users/me" : null);

  useEffect(() => {
    if (!token.get()) window.location.replace("/login");
    else setReady(true);
  }, []);
  useEffect(() => setMenu(false), [path]);
  if (!ready) return <Loading />;

  const nav = (
    <nav aria-label="Main" className="space-y-1 p-3">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = path === href || path.startsWith(href + "/");
        return (
          <Link key={href} href={href} aria-current={active ? "page" : undefined}
            className={cx("flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium", active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100")}>
            <Icon className="h-4 w-4" /> {label}
          </Link>
        );
      })}
    </nav>
  );
  return (
    <div className="min-h-screen lg:flex">
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:block">
        <div className="px-6 py-5 text-lg font-bold text-brand-700">JobPilot</div>
        {nav}
      </aside>
      {menu && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setMenu(false)} />
          <aside className="relative h-full w-64 bg-white shadow-xl">
            <div className="flex items-center justify-between px-6 py-5 text-lg font-bold text-brand-700">JobPilot <button aria-label="Close menu" onClick={() => setMenu(false)}><X className="h-5 w-5" /></button></div>
            {nav}
          </aside>
        </div>
      )}
      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-2 backdrop-blur">
          <button className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 lg:hidden" aria-label="Open menu" onClick={() => setMenu(true)}><Menu className="h-5 w-5" /></button>
          <div className="hidden text-sm text-slate-500 lg:block">{me?.email}</div>
          <div className="flex items-center gap-1">
            <Bell_ />
            <button onClick={async () => { try { await api("/api/auth/logout", { method: "POST" }); } catch {} token.clear(); window.location.href = "/login"; }}
              className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">Log out</button>
          </div>
        </header>
        <main className="mx-auto max-w-7xl p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}
