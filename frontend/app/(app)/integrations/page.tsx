"use client";
import { fmtDate, useApi } from "@/lib/api";
import { Card, ErrorBox, Loading, Notice, PageHeader } from "@/components/ui";

const tone: Record<string, string> = { ok: "bg-emerald-100 text-emerald-800", unavailable: "bg-red-100 text-red-700", unused: "bg-slate-100 text-slate-600" };

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
                <div className="mt-1 text-xs text-slate-500">{x.configured_boards} board(s) configured · last success {fmtDate(x.last_success_at)}{x.last_error && <span className="text-red-600"> · last error: {x.last_error}</span>}</div></div>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone[x.status]}`}>{x.status === "ok" ? "Healthy" : x.status === "unavailable" ? "Unavailable" : "Not used yet"}</span>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">Add company boards (e.g. Greenhouse board token “gitlab”) under Job Search Preferences → Sources. None of these sources need credentials.</p>
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
