"use client";
import Link from "next/link";
import { useState } from "react";
import { fmtDate, useApi } from "@/lib/api";
import { Card, Empty, ErrorBox, Loading, Notice, PageHeader, Stat } from "@/components/ui";

export default function Reports() {
  const { data, error, loading } = useApi<any[]>("/api/reports/daily?limit=30");
  const [sel, setSel] = useState<number | null>(null);
  if (loading) return <Loading />;
  const r = data?.find((x) => x.id === sel) || data?.[0];
  return (
    <>
      <PageHeader title="Daily Reports" subtitle="One report per search run: what was found, what needs you, and what failed." />
      <ErrorBox message={error} />
      {!data?.length ? <Empty title="No reports yet" hint="A report is created after each search run (manual or scheduled)." /> : (
        <div className="grid gap-4 lg:grid-cols-4">
          <Card title="Runs" className="lg:col-span-1">
            <ul className="space-y-1">{data.map((x) => (
              <li key={x.id}><button onClick={() => setSel(x.id)} className={`w-full rounded-lg px-2 py-2 text-left text-sm ${x.id === r.id ? "bg-brand-50 text-brand-700" : "hover:bg-slate-50"}`}>
                <div className="font-medium">{fmtDate(x.run_time)}</div><div className="text-xs text-slate-500">{x.profile} · {x.new_unique_jobs} new · {x.run_status}</div></button></li>))}</ul>
          </Card>
          <div className="space-y-4 lg:col-span-3">
            <Notice tone={r.no_new_jobs ? "info" : "ok"}>{r.summary}</Notice>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Listings retrieved" value={r.listings_retrieved} /><Stat label="New unique jobs" value={r.new_unique_jobs} />
              <Stat label="Matching filters" value={r.matching_jobs} /><Stat label="Resumes generated" value={r.resumes_generated} />
              <Stat label="Ready for review" value={r.ready_for_review} /><Stat label="Ready to apply" value={r.ready_to_apply} />
              <Stat label="Submitted & confirmed" value={r.applications_submitted} /><Stat label="Manual action" value={r.applications_manual_action} />
              <Stat label="Jobs skipped" value={r.jobs_skipped} /><Stat label="Failed tasks" value={r.failed_tasks} /><Stat label="Closed listings" value={r.closed_listings} />
            </div>
            <Card title="Sources">
              <div className="space-y-1 text-sm">
                {r.sources_searched.map((s: string) => <div key={s} className="text-emerald-700">✓ {s}</div>)}
                {Object.entries(r.sources_failed).map(([s, e]) => <div key={s} className="text-red-700">✕ {s}: {String(e)}</div>)}
              </div>
            </Card>
            {Object.keys(r.skipped_reasons).length > 0 && <Card title="Why jobs were skipped"><ul className="text-sm">{Object.entries(r.skipped_reasons).map(([k, n]) => <li key={k}>{k.replace(/_/g, " ")}: {String(n)}</li>)}</ul></Card>}
            {r.errors && <Card title="Needs attention"><p className="text-sm text-red-700">{r.errors}</p></Card>}
            <Card title="New qualifying jobs">
              {r.new_jobs.length === 0 ? <p className="text-sm text-slate-500">No new qualifying jobs were found during this run.</p> :
                <ul className="divide-y divide-slate-100">{r.new_jobs.map((j: any) => <li key={j.job_id} className="flex justify-between py-2 text-sm"><Link className="text-brand-700 hover:underline" href={`/jobs/${j.job_id}`}>{j.title} · {j.company}</Link><span className="text-slate-500">{Math.round(j.score)}</span></li>)}</ul>}
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
