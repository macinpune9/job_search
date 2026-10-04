"use client";
import Link from "next/link";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDate, useApi } from "@/lib/api";
import { Card, Empty, ErrorBox, Loading, PageHeader, Stat, StatusBadge } from "@/components/ui";

export default function Dashboard() {
  const { data: d, error, loading } = useApi<any>("/api/dashboard");
  const { data: runs } = useApi<any[]>("/api/search-runs?limit=10");
  const { data: resumes } = useApi<any[]>("/api/resumes");
  const { data: profiles } = useApi<any[]>("/api/search-profiles");
  if (loading) return <Loading />;
  if (error || !d) return <ErrorBox message={error} />;
  const funnel = [
    { name: "Discovered", v: d.total_jobs_discovered }, { name: "Matching", v: d.matching_jobs },
    { name: "Ready/review", v: d.ready_for_review_or_apply }, { name: "Submitted", v: d.applications_submitted },
  ];
  const nothingYet = d.total_jobs_discovered === 0;
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Live numbers from your search history." />
      {(() => {
        const steps = [
          { done: (resumes || []).length > 0, label: "Upload your CV", href: "/resumes", hint: "PDF or DOCX" },
          { done: (profiles || []).some((p) => (p.keywords || []).length > 0), label: "Review your career snapshot", href: "/resumes", hint: "one click fills in your search" },
          { done: (profiles || []).some((p) => (p.sources || []).length > 0), label: "Choose where to search", href: "/preferences", hint: "company career feeds, Adzuna…" },
          { done: (runs || []).length > 0, label: "Run your first search", href: "/preferences", hint: "partial matches (40–50%) are shown too" },
        ];
        if (!resumes || !profiles || !runs || steps.every((s) => s.done)) return null;
        return (
          <div className="mb-6 rounded-xl border border-brand-200 bg-brand-50 p-4">
            <div className="mb-2 text-sm font-semibold text-slate-800">Getting started: {steps.filter((s) => s.done).length} of {steps.length} done</div>
            <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {steps.map((s, i) => (
                <li key={i}><Link href={s.href} className={`block rounded-lg border px-3 py-2 text-sm ${s.done ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-800 hover:border-brand-500"}`}>
                  <span className="font-medium">{s.done ? "✓ " : `${i + 1}. `}{s.label}</span><span className="block text-xs text-slate-500">{s.hint}</span></Link></li>
              ))}
            </ol>
          </div>);
      })()}
      {nothingYet && (
        <div className="mb-6"><Empty title="No jobs discovered yet" hint="Upload a resume, create a search profile with at least one job source, then run a search."
          action={<div className="flex justify-center gap-2"><Link className="text-brand-600 underline" href="/resumes">Upload resume</Link><Link className="text-brand-600 underline" href="/preferences">Set up search</Link></div>} /></div>
      )}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Jobs discovered" value={d.total_jobs_discovered} />
        <Stat label="New (24h)" value={d.new_jobs_24h} />
        <Stat label="Matching criteria" value={d.matching_jobs} />
        <Stat label="Ready for review/apply" value={d.ready_for_review_or_apply} />
        <Stat label="Applications submitted" value={d.applications_submitted} />
        <Stat label="Need manual action" value={d.manual_action_required} />
        <Stat label="Interviews" value={d.interviews} />
        <Stat label="Search runs completed" value={d.search_runs_completed} />
      </div>
      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card title="Pipeline" className="lg:col-span-2">
          <div className="h-56" aria-label="Pipeline chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnel}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="name" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} /><Tooltip />
                <Bar dataKey="v" fill="#4f46e5" radius={[4, 4, 0, 0]} /></BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
        <Card title="Schedule">
          <dl className="space-y-3 text-sm">
            <div><dt className="text-slate-500">Last successful run</dt><dd className="font-medium">{fmtDate(d.last_successful_run)}</dd></div>
            <div><dt className="text-slate-500">Next scheduled search</dt><dd className="font-medium">{d.automation_paused ? "Paused" : fmtDate(d.next_scheduled_search)}</dd></div>
            <div><dt className="text-slate-500">Recent runs</dt>
              <dd className="mt-1 space-y-1">{(runs || []).slice(0, 4).map((r) => <div key={r.id} className="flex justify-between text-xs"><span>{fmtDate(r.started_at)}</span><span className={r.status === "completed" ? "text-emerald-700" : r.status === "failed" ? "text-red-600" : "text-amber-700"}>{r.status}</span></div>)}
                {(runs || []).length === 0 && <span className="text-slate-400">None yet</span>}</dd></div>
          </dl>
        </Card>
      </div>
      <Card title="Recent application activity" className="mt-6">
        {d.recent_activity.length === 0 ? <p className="text-sm text-slate-500">No application activity yet.</p> : (
          <ul className="divide-y divide-slate-100">
            {d.recent_activity.map((a: any, i: number) => (
              <li key={i} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <Link href={`/history/${a.application_id}`} className="font-medium text-slate-800 hover:underline">{a.title} · {a.company}</Link>
                <span className="flex items-center gap-2 text-slate-500">{a.event.replace(/_/g, " ")} {a.status && <StatusBadge status={a.status} />} <span className="text-xs">{fmtDate(a.at)}</span></span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
