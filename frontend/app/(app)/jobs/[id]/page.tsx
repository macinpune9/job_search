"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, fmtDate, useApi } from "@/lib/api";
import { Button, Card, Chip, ErrorBox, Loading, Notice, PageHeader, ScoreBadge, StatusBadge, useToast } from "@/components/ui";

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: j, error, loading, reload } = useApi<any>(`/api/jobs/${id}`);
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();
  if (loading && !j) return <Loading />;
  if (error || !j) return <ErrorBox message={error} />;
  const m = j.match, rv = (j.resume_versions || []).find((v: any) => v.id === j.recommended_resume_version_id) || j.resume_versions?.[0];
  const an = rv?.analysis;

  async function prepare(cover: boolean) {
    setBusy(true);
    try {
      const r = await api(`/api/jobs/${id}/prepare-application`, { body: { cover_letter: cover } });
      toast(r.created ? "Application prepared. Review the resume before approving." : "An application already exists for this job.");
      await reload();
    } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }
  const sal = j.salary_information;
  return (
    <>
      {node}
      <PageHeader title={j.title} subtitle={`${j.company_name} · ${j.location || "Location not stated"}`}
        actions={j.application
          ? <Link href={`/history/${j.application.id}`}><Button>Open application</Button></Link>
          : <><Button variant="secondary" busy={busy} disabled={j.status !== "open"} onClick={() => prepare(true)}>Prepare with cover letter</Button><Button busy={busy} disabled={j.status !== "open"} onClick={() => prepare(false)}>Prepare application</Button></>} />
      {j.status !== "open" && <div className="mb-4"><Notice tone="warn">This listing is no longer open at its source.</Notice></div>}
      {j.listings.some((l: any) => l.source_metadata?.description_truncated) && <div className="mb-4"><Notice tone="warn">This source only provides a short snippet of the description, so matching and resume tailoring have less to work with. Open the original listing, copy the full text, and use <b>Add job manually</b> if you want a full match.</Notice></div>}
      {j.listings.some((l: any) => l.source_metadata?.imported_by_user) && <div className="mb-4"><Notice>You added this job manually. It is shown even if it would normally be filtered out; the reasons are listed below.</Notice></div>}
      {j.needs_dedup_review && <div className="mb-4"><Notice tone="warn">Possible duplicate of job #{j.possible_duplicate_of}: same company/title/location but a different description. Not merged automatically.</Notice></div>}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <Card title="Job description (original)"><pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap font-sans text-sm text-slate-700">{j.description || "No description provided."}</pre></Card>
          {an && (
            <Card title={`Resume analysis (version v${rv.version_number})`}>
              <div className="space-y-3 text-sm">
                <div><div className="mb-1 font-medium">Matched skills & terms</div><div className="flex flex-wrap gap-1">{an.matched_skills.map((s: string) => <Chip key={s} tone="green">{s}</Chip>)}{an.matched_skills.length === 0 && <span className="text-slate-400">None found</span>}</div></div>
                <div><div className="mb-1 font-medium">Missing / unsupported requirements (not added to your resume)</div><div className="flex flex-wrap gap-1">{an.missing_requirements.map((s: string) => <Chip key={s} tone="amber">{s}</Chip>)}{an.missing_requirements.length === 0 && <span className="text-slate-400">None detected</span>}</div></div>
                <div>Keyword coverage: <b>{an.keyword_coverage == null ? "n/a" : `${Math.round(an.keyword_coverage * 100)}%`}</b></div>
              </div>
            </Card>
          )}
        </div>
        <div className="space-y-4">
          <Card title="Status">
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">Workflow <StatusBadge status={j.application?.status || m.workflow_status} /></div>
              <div className="flex items-center justify-between">Match score <ScoreBadge score={m.match_score} /></div>
              <div className="rounded-lg bg-slate-50 p-2 text-slate-700"><b>Next:</b> {j.next_action}</div>
              <div className="text-slate-500">Application method: {j.application_method}</div>
            </div>
          </Card>
          <Card title="Details">
            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 text-sm">
              <dt className="text-slate-500">Employment</dt><dd>{j.employment_type?.replace(/_/g, " ") || "—"}</dd>
              <dt className="text-slate-500">Work mode</dt><dd>{j.remote_status}</dd>
              <dt className="text-slate-500">Salary</dt><dd>{sal ? `${sal.min ?? "?"}–${sal.max ?? "?"} ${sal.currency || ""}${sal.period ? "/" + sal.period : ""}` : "Not stated"}</dd>
              <dt className="text-slate-500">Posted</dt><dd>{j.posted_at ? fmtDate(j.posted_at) : "Unknown (no reliable date)"}</dd>
              <dt className="text-slate-500">Discovered</dt><dd>{fmtDate(j.first_discovered_at)}</dd>
              <dt className="text-slate-500">Closing</dt><dd>{j.closing_date ? fmtDate(j.closing_date) : "—"}</dd>
            </dl>
          </Card>
          <Card title="Why it matched / was excluded">
            <ul className="space-y-1.5 text-sm">
              {m.exclusion_reasons.map((e: any, i: number) => <li key={i} className="text-red-700">✕ {e.code.replace(/_/g, " ")}: {e.detail}</li>)}
              {m.matching_factors.map((f: any, i: number) => <li key={i} className="text-slate-700">{f.weight ? <b>{f.name} {f.earned}/{f.weight}</b> : <b>{f.name}</b>} — {f.detail}</li>)}
            </ul>
          </Card>
          <Card title="Source links">
            <ul className="space-y-1 text-sm">
              {j.listings.map((l: any) => (
                <li key={l.id}><span className="font-medium">{l.source_name}</span> {l.status === "closed" && "(closed) "}
                  <a className="break-all text-brand-700 hover:underline" href={l.source_url} target="_blank" rel="noopener noreferrer">listing</a>
                  {l.application_url && <> · <a className="text-brand-700 hover:underline" href={l.application_url} target="_blank" rel="noopener noreferrer">apply</a></>}</li>
              ))}
              {j.company_career_url && <li><a className="text-brand-700 hover:underline" href={j.company_career_url} target="_blank" rel="noopener noreferrer">Company careers page</a></li>}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}
