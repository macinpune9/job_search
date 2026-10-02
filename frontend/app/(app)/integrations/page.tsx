"use client";
import { fmtDate, useApi } from "@/lib/api";
import { Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";

const tone: Record<string, string> = { ok: "bg-emerald-100 text-emerald-800", unavailable: "bg-red-100 text-red-700", unused: "bg-slate-100 text-slate-600", needs_configuration: "bg-amber-100 text-amber-800" };
const label: Record<string, string> = { ok: "Healthy", unavailable: "Unavailable", unused: "Not used yet", needs_configuration: "Needs API key" };

export default function Integrations() {
  const { data: s, error, loading } = useApi<any[]>("/api/sources");
  const { data: i } = useApi<any>("/api/integrations");
  if (loading) return <Loading />;
  return (
    <>
      <PageHeader title="Integrations" subtitle="Where jobs come from and how applications can be submitted. This is not “every job site on the internet”; only the sources listed here are searched." />
      <ErrorBox message={error} />
      <Card title="Job sources">
        <div className="divide-y divide-slate-100">
          {(s || []).map((x) => (
            <div key={x.name} className="flex flex-wrap items-start justify-between gap-2 py-3">
              <div><div className="font-medium">{x.display_name}</div><div className="text-sm text-slate-500">{x.compliance_note}</div>
                <div className="mt-1 text-xs text-slate-500">Board field: {x.board_hint}{x.board_example ? <> (e.g. <code>{x.board_example}</code>)</> : null}</div>
                {x.requires_credentials && !x.configured && <div className="mt-1 text-xs text-amber-700">{x.credentials_help}</div>}
                <div className="mt-1 text-xs text-slate-500">{x.configured_boards} board(s) configured · last success {fmtDate(x.last_success_at)}{x.last_error && <span className="text-red-600"> · last error: {x.last_error}</span>}</div></div>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone[x.status]}`}>{label[x.status] || x.status}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">Add boards or searches under Job Search Preferences → Job sources.</p>
      </Card>
      <Card title="LinkedIn, Indeed, jobs.ch and similar sites" className="mt-4">
        <div className="space-y-2 text-sm text-slate-700">
          <p>These cannot be searched automatically, on purpose: LinkedIn and Indeed offer no public job-search API and forbid automated collection, and jobs.ch&apos;s robots.txt disallows automated access to its API and job pages. Scraping them would risk your accounts and break the sites&apos; rules.</p>
          <p><b>What you can do instead:</b> find the job yourself, then use <b>Discovered Jobs → Add job manually</b> and paste its text. It gets matched, scored, tailored and tracked like any other job. For breadth, add the career feeds of Swiss employers that use Personio, SmartRecruiters, Workable, Recruitee, Greenhouse, Lever or Ashby, or enable Adzuna for Switzerland-wide search.</p>
        </div>
      </Card>
      {i && (
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <Card title="Application submission">
            {i.submitters.map((x: any) => <div key={x.name} className="text-sm"><b>{x.name}</b> {x.active ? "(active)" : "(inactive)"}<div className="text-slate-500">{x.note}</div></div>)}
            <div className="mt-2"><Notice>No employer-authorized submission API is configured. Without one, applications use the manual package.</Notice></div>
          </Card>
          <Card title="LinkedIn"><p className="text-sm">{i.linkedin.mode}</p><p className="text-sm text-slate-500">{i.linkedin.note}</p></Card>
          <Card title="AI provider"><p className="text-sm"><b>{i.ai_provider.name}</b></p><p className="text-sm text-slate-500">{i.ai_provider.note}</p></Card>
        </div>
      )}
    </>
  );
}
