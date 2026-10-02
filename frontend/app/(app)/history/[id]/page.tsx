"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, fmtDate, openSigned, useApi } from "@/lib/api";
import { Button, Card, Chip, ErrorBox, Field, Input, Loading, Notice, PageHeader, StatusBadge, Textarea, useToast } from "@/components/ui";

function Resume({ c }: { c: any }) {
  return (
    <div className="space-y-3 text-sm">
      <div className="font-semibold">{c.name}</div>
      {c.summary && <p className="text-slate-600">{c.summary}</p>}
      <div><div className="text-xs font-semibold uppercase text-slate-400">Skills</div>{(c.skills || []).join(", ")}</div>
      {(c.experience || []).map((e: any, i: number) => (
        <div key={i}><div className="font-medium">{e.title}, {e.company}</div><div className="text-xs text-slate-400">{e.start} – {e.end}</div>
          <ul className="ml-4 list-disc">{e.bullets.map((b: string, j: number) => <li key={j}>{b}</li>)}</ul></div>
      ))}
      {(c.education || []).length > 0 && <div><div className="text-xs font-semibold uppercase text-slate-400">Education</div>{c.education.map((e: any, i: number) => <div key={i}>{e.text}</div>)}</div>}
      {(c.certifications || []).length > 0 && <div><div className="text-xs font-semibold uppercase text-slate-400">Certifications</div>{c.certifications.join("; ")}</div>}
    </div>
  );
}

export default function ApplicationDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: a, error, loading, reload } = useApi<any>(`/api/applications/${id}`);
  const [busy, setBusy] = useState("");
  const [notes, setNotes] = useState<string | null>(null);
  const [follow, setFollow] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const { toast, node } = useToast();
  const { data: orig } = useApi<any>(a?.original_resume_id ? `/api/resumes/${a.original_resume_id}` : null);
  if (loading && !a) return <Loading />;
  if (error || !a) return <ErrorBox message={error} />;
  const rv = a.resume_version, v = rv?.validation_results, an = rv?.analysis;
  const locked = ["submitted", "interview", "offer_received", "rejected", "application_in_progress", "closed_or_expired", "withdrawn", "submission_confirmation_pending"].includes(a.status);

  async function act(name: string, fn: () => Promise<any>, ok: string) {
    setBusy(name);
    try { await fn(); toast(ok); await reload(); } catch (e: any) { toast(e.message, "err"); } finally { setBusy(""); }
  }
  async function saveEdit() {
    let content;
    try { content = JSON.parse(draft); } catch { return toast("Not valid JSON", "err"); }
    await act("edit", async () => {
      const nv = await api(`/api/resume-versions/${rv.id}/edit`, { body: { content } });
      await api(`/api/applications/${a.id}`, { method: "PATCH", body: { resume_version_id: nv.id } });
      setEditing(false);
    }, "Saved as a new version and re-validated");
  }
  const setStatus = (s: string) => act("st", () => api(`/api/applications/${a.id}`, { method: "PATCH", body: { status: s } }), `Marked ${s.replace(/_/g, " ")}`);

  return (
    <>
      {node}
      <PageHeader title={a.job_title} subtitle={`${a.company} · ${a.location || ""}`} actions={<StatusBadge status={a.status} />} />
      <div className="mb-4 flex flex-wrap gap-2">
        {["awaiting_user_approval", "manual_application_required", "resume_ready_for_review"].includes(a.status) && !a.approved_at && (
          <Button busy={busy === "ap"} disabled={!v?.passed} onClick={() => act("ap", () => api(`/api/applications/${a.id}/approve`, { method: "POST" }), "Approved")}>Approve resume{a.cover_letter ? " & cover letter" : ""}</Button>
        )}
        {["ready_to_apply", "application_failed"].includes(a.status) && <Button busy={busy === "sub"} onClick={() => act("sub", () => api(`/api/applications/${a.id}/submit`, { method: "POST" }), "Submission attempted")}>{a.status === "application_failed" ? "Retry submission" : "Submit application"}</Button>}
        {a.status === "manual_application_required" && <>
          {a.application_url && <a href={a.application_url} target="_blank" rel="noopener noreferrer"><Button variant="secondary">Open employer application page</Button></a>}
          <Button variant="secondary" busy={busy === "st"} onClick={() => { if (confirm("Only mark as submitted if you actually completed the application on the employer's site. This is recorded as your own attestation.")) setStatus("submitted"); }}>I applied — mark submitted</Button></>}
        {a.status === "submission_confirmation_pending" && <Button variant="secondary" onClick={() => { if (confirm("Confirm you verified with the employer that the application was received?")) setStatus("submitted"); }}>I verified it was received</Button>}
        {["submitted", "interview"].includes(a.status) && <>{a.status === "submitted" && <Button variant="secondary" onClick={() => setStatus("interview")}>Interview</Button>}<Button variant="secondary" onClick={() => setStatus("offer_received")}>Offer</Button><Button variant="secondary" onClick={() => setStatus("rejected")}>Rejected</Button></>}
        {!locked && <Button variant="ghost" onClick={() => setStatus("withdrawn")}>Withdraw</Button>}
        <Link href={`/jobs/${a.job_id}`}><Button variant="ghost">Job page</Button></Link>
      </div>
      {a.manual_reason && <div className="mb-4"><Notice tone="warn"><b>Manual action:</b> {a.manual_reason}</Notice></div>}
      {a.status === "submission_confirmation_pending" && <div className="mb-4"><Notice tone="warn">The outcome of the submission could not be confirmed. It will not be retried automatically to avoid a duplicate application. Check with the employer.</Notice></div>}
      {a.status === "submitted" && <div className="mb-4"><Notice tone="ok">Submitted {fmtDate(a.date_applied)} via {a.submission_method}{a.external_reference ? `, reference ${a.external_reference}` : ""}. {a.events.some((e: any) => e.event_type === "user_attested_submission") && "Recorded from your own confirmation."}</Notice></div>}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={`Tailored resume v${rv?.version_number ?? "–"}`} actions={<>
          {rv?.has_docx && <Button variant="secondary" onClick={() => openSigned(`/api/resume-versions/${rv.id}/download-link?fmt=docx`)}>DOCX</Button>}
          {rv?.has_pdf && <Button variant="secondary" onClick={() => openSigned(`/api/resume-versions/${rv.id}/download-link?fmt=pdf`)}>PDF</Button>}
          {!locked && <Button variant="secondary" onClick={() => { setEditing(!editing); setDraft(JSON.stringify(rv.generated_content, null, 2)); }}>{editing ? "Cancel" : "Edit"}</Button>}</>}>
          {editing ? (
            <div className="space-y-2"><Notice>Edits create a new version and are re-checked against your original resume. Unsupported skills, roles, numbers or credentials will block approval.</Notice>
              <Textarea rows={22} value={draft} onChange={(e) => setDraft(e.target.value)} className="font-mono text-xs" /><Button busy={busy === "edit"} onClick={saveEdit}>Save new version</Button></div>
          ) : rv ? <Resume c={rv.generated_content} /> : <p className="text-sm text-slate-500">No resume attached.</p>}
        </Card>
        <Card title="Original resume (source of truth)">{orig?.structured_profile ? <Resume c={orig.structured_profile} /> : <Loading />}</Card>
        <Card title="Factual validation">
          {v ? (
            <div className="space-y-2 text-sm">
              <div className={v.passed ? "font-medium text-emerald-700" : "font-medium text-red-700"}>{v.passed ? "✓ Passed: no unsupported facts detected" : "✕ Failed: fix before approving"}</div>
              {v.issues.length === 0 && <p className="text-slate-500">Every skill, role, date and number traces back to your original resume.</p>}
              <ul className="space-y-1">{v.issues.map((i: any, k: number) => <li key={k} className={i.severity === "error" ? "text-red-700" : "text-amber-700"}>{i.severity === "error" ? "✕" : "!"} {i.code.replace(/_/g, " ")}: {i.detail}</li>)}</ul>
            </div>) : null}
        </Card>
        <Card title="Match & changes">
          {an ? (
            <div className="space-y-3 text-sm">
              <div><div className="mb-1 font-medium">Matched</div><div className="flex flex-wrap gap-1">{an.matched_skills.map((s: string) => <Chip key={s} tone="green">{s}</Chip>)}</div></div>
              <div><div className="mb-1 font-medium">Gaps (not claimed)</div><div className="flex flex-wrap gap-1">{an.missing_requirements.map((s: string) => <Chip key={s} tone="amber">{s}</Chip>)}</div></div>
              <div><div className="mb-1 font-medium">Changes made and why</div>
                {an.changes.length === 0 ? <p className="text-slate-500">No changes: already in the best order.</p> : <ul className="list-disc pl-5">{an.changes.map((c: any, i: number) => <li key={i}>{c.detail} <span className="text-slate-500">— {c.reason}</span></li>)}</ul>}</div>
              <p className="text-xs text-slate-500">ATS compatibility is improved with simple formatting and standard headings; no tool can guarantee every ATS will parse a resume.</p>
            </div>) : null}
        </Card>
        {a.cover_letter && <Card title={`Cover letter v${a.cover_letter.version_number}`}><pre className="whitespace-pre-wrap font-sans text-sm">{a.cover_letter.content}</pre>
          <p className="mt-2 text-xs text-slate-500">{a.cover_letter.validation_results.passed ? "Validated against your resume." : "Contains unsupported claims."}</p></Card>}
        {a.package && <Card title="Manual application package">
          <div className="space-y-2 text-sm">
            <div><b>Apply at:</b> {a.package.application_url ? <a className="break-all text-brand-700 hover:underline" href={a.package.application_url} target="_blank" rel="noopener noreferrer">{a.package.application_url}</a> : "—"}</div>
            <div><b>Suggested answers (from verified data only):</b><ul className="ml-4 list-disc">{Object.entries(a.package.suggested_answers || {}).map(([k, val]) => <li key={k}>{k.replace(/_/g, " ")}: {typeof val === "string" ? val : JSON.stringify(val)}</li>)}</ul></div>
            <div><b>You need to:</b><ul className="ml-4 list-disc">{a.package.checklist.map((c: string) => <li key={c}>{c}</li>)}</ul></div>
          </div></Card>}
        <Card title="Notes & follow-up">
          <div className="space-y-3">
            <Field label="Notes"><Textarea rows={3} defaultValue={a.notes || ""} onChange={(e) => setNotes(e.target.value)} /></Field>
            <Field label="Follow-up date"><Input type="date" defaultValue={a.follow_up_date?.slice(0, 10) || ""} onChange={(e) => setFollow(e.target.value)} /></Field>
            <Button variant="secondary" busy={busy === "n"} onClick={() => act("n", () => api(`/api/applications/${a.id}`, { method: "PATCH", body: { ...(notes !== null ? { notes } : {}), ...(follow !== null ? { follow_up_date: follow ? new Date(follow).toISOString() : null } : {}) } }), "Saved")}>Save</Button>
          </div>
        </Card>
        <Card title="Job description (original)"><pre className="max-h-96 overflow-auto whitespace-pre-wrap font-sans text-sm">{a.job.description}</pre>
          <div className="mt-2 text-xs text-slate-500">Sources: {a.job.listings.map((l: any) => <a key={l.id} className="mr-2 text-brand-700 hover:underline" href={l.source_url} target="_blank" rel="noopener noreferrer">{l.source_name}</a>)}</div></Card>
        <Card title="Status history (immutable)" className="xl:col-span-2">
          <ol className="space-y-2 text-sm">
            {a.events.map((e: any) => (
              <li key={e.id} className="flex flex-wrap items-center gap-2 border-l-2 border-brand-200 pl-3">
                <span className="w-44 text-xs text-slate-400">{fmtDate(e.event_timestamp)}</span>
                <span className="font-medium">{e.event_type.replace(/_/g, " ")}</span>
                {e.new_status && <StatusBadge status={e.new_status} />}
                <span className="text-xs text-slate-400">by {e.actor_type}</span>
                {Object.keys(e.details || {}).length > 0 && <span className="text-xs text-slate-500">{JSON.stringify(e.details)}</span>}
              </li>
            ))}
          </ol>
        </Card>
      </div>
    </>
  );
}
