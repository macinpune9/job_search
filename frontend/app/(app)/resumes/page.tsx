"use client";
import { useEffect, useRef, useState } from "react";
import { api, fmtDate, openSigned, useApi } from "@/lib/api";
import { Button, Card, Chip, Empty, ErrorBox, Field, Input, Loading, Notice, PageHeader, Table, Td, Textarea, Th, useToast } from "@/components/ui";

function Editor({ resume, onSaved }: { resume: any; onSaved: () => void }) {
  const [p, setP] = useState<any>(resume.structured_profile);
  const [busy, setBusy] = useState(false);
  const { toast, node } = useToast();
  useEffect(() => setP(resume.structured_profile), [resume.id, resume.structured_profile]);
  if (!p) return null;
  const set = (k: string, v: any) => setP({ ...p, [k]: v });
  const setExp = (i: number, k: string, v: any) => set("experience", p.experience.map((e: any, j: number) => (j === i ? { ...e, [k]: v } : e)));
  const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  async function save() {
    setBusy(true);
    try { await api(`/api/resumes/${resume.id}`, { method: "PATCH", body: { structured_profile: p } }); toast("Saved. Future tailored resumes use these corrections."); onSaved(); } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-4">
      {node}
      <Notice>Automatic parsing is best-effort. Check every field: this reviewed profile is the <b>only</b> source of facts for tailored resumes, so anything missing here can never appear in one.</Notice>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Name"><Input value={p.name || ""} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Email"><Input value={p.email || ""} onChange={(e) => set("email", e.target.value)} /></Field>
        <Field label="Phone"><Input value={p.phone || ""} onChange={(e) => set("phone", e.target.value)} /></Field>
      </div>
      <Field label="Summary"><Textarea rows={3} value={p.summary || ""} onChange={(e) => set("summary", e.target.value)} /></Field>
      <Field label="Skills" hint="Comma separated"><Textarea rows={2} value={(p.skills || []).join(", ")} onChange={(e) => set("skills", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} /></Field>
      <div className="space-y-3">
        <div className="text-sm font-medium text-slate-700">Experience</div>
        {p.experience.map((e: any, i: number) => (
          <div key={i} className="space-y-2 rounded-lg border border-slate-200 p-3">
            <div className="grid gap-2 sm:grid-cols-4">
              <Input aria-label="Title" placeholder="Title" value={e.title} onChange={(x) => setExp(i, "title", x.target.value)} />
              <Input aria-label="Company" placeholder="Company" value={e.company} onChange={(x) => setExp(i, "company", x.target.value)} />
              <Input aria-label="Start" placeholder="Start (YYYY-MM)" value={e.start || ""} onChange={(x) => setExp(i, "start", x.target.value)} />
              <Input aria-label="End" placeholder="End (YYYY-MM or present)" value={e.end || ""} onChange={(x) => setExp(i, "end", x.target.value)} />
            </div>
            <Textarea aria-label="Bullets" rows={4} placeholder="One achievement/responsibility per line" value={e.bullets.join("\n")} onChange={(x) => setExp(i, "bullets", lines(x.target.value))} />
            <Button variant="ghost" onClick={() => set("experience", p.experience.filter((_: any, j: number) => j !== i))}>Remove role</Button>
          </div>
        ))}
        <Button variant="secondary" onClick={() => set("experience", [...p.experience, { title: "", company: "", start: "", end: "", bullets: [] }])}>Add role</Button>
      </div>
      <Field label="Education" hint="One entry per line"><Textarea rows={3} value={(p.education || []).map((x: any) => x.text).join("\n")} onChange={(e) => set("education", lines(e.target.value).map((t) => ({ text: t, degree: null, year: (t.match(/(19|20)\d{2}/) || [null])[0] })))} /></Field>
      <Field label="Certifications" hint="One per line"><Textarea rows={2} value={(p.certifications || []).join("\n")} onChange={(e) => set("certifications", lines(e.target.value))} /></Field>
      <Field label="Achievements" hint="One per line"><Textarea rows={2} value={(p.achievements || []).join("\n")} onChange={(e) => set("achievements", lines(e.target.value))} /></Field>
      <Button busy={busy} onClick={save}>Save corrections</Button>
    </div>
  );
}

export default function Resumes() {
  const { data: list, loading, error, reload } = useApi<any[]>("/api/resumes");
  const [sel, setSel] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [upErr, setUpErr] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const { toast, node } = useToast();
  const cur = list?.find((r) => r.id === sel) || list?.[0];
  const { data: detail, reload: reloadDetail } = useApi<any>(cur ? `/api/resumes/${cur.id}` : null);
  const { data: versions } = useApi<any[]>(cur ? `/api/resumes/${cur.id}/versions` : null);
  const [tab, setTab] = useState<"profile" | "text" | "versions">("profile");

  async function upload(f: File) {
    setUploading(true); setUpErr(null);
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api("/api/resumes", { form: fd }); setSel(r.id); toast("Resume uploaded and parsed"); await reload(); }
    catch (e: any) { setUpErr(e.message); await reload(); } finally { setUploading(false); if (file.current) file.current.value = ""; }
  }
  return (
    <>
      {node}
      <PageHeader title="Resume Manager" subtitle="Your uploaded resume is preserved exactly and is the only source of facts for tailored versions."
        actions={<><input ref={file} type="file" accept=".pdf,.docx" className="hidden" aria-label="Upload resume" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          <Button busy={uploading} onClick={() => file.current?.click()}>Upload PDF or DOCX</Button></>} />
      <ErrorBox message={upErr || error} />
      {loading && !list ? <Loading /> : !list?.length ? <Empty title="No resumes yet" hint="Upload a PDF or DOCX (up to 5 MB). Password-protected, corrupted, scanned-image or empty files are rejected with a clear message." /> : (
        <div className="mt-4 grid gap-4 lg:grid-cols-4">
          <Card title="Your resumes" className="lg:col-span-1">
            <ul className="space-y-1">{list.map((r) => (
              <li key={r.id}><button onClick={() => setSel(r.id)} className={`w-full rounded-lg px-2 py-2 text-left text-sm ${r.id === cur?.id ? "bg-brand-50 text-brand-700" : "hover:bg-slate-50"}`}>
                <div className="truncate font-medium">{r.label || r.filename}</div>
                <div className="flex items-center gap-1 text-xs text-slate-500">{r.file_type.toUpperCase()} · {fmtDate(r.uploaded_at)}</div>
                <div className="mt-1 flex gap-1">{r.is_primary && <Chip tone="green">primary</Chip>}<Chip tone={r.processing_status === "parsed" ? "slate" : "red"}>{r.processing_status}</Chip></div></button></li>))}</ul>
          </Card>
          <div className="lg:col-span-3">
            {cur && detail && (
              <Card title={cur.label || cur.filename} actions={<>
                <Button variant="secondary" onClick={() => openSigned(`/api/resumes/${cur.id}/download-link`)}>Download original</Button>
                {!cur.is_primary && <Button variant="secondary" onClick={async () => { await api(`/api/resumes/${cur.id}`, { method: "PATCH", body: { is_primary: true } }); reload(); }}>Make primary</Button>}
                <Button variant="danger" onClick={async () => { if (!confirm("Delete this resume and its generated versions?")) return; try { await api(`/api/resumes/${cur.id}`, { method: "DELETE" }); setSel(null); reload(); } catch (e: any) { toast(e.message, "err"); } }}>Delete</Button></>}>
                <div className="mb-4 flex gap-2 border-b border-slate-200 text-sm">
                  {(["profile", "text", "versions"] as const).map((t) => <button key={t} onClick={() => setTab(t)} className={`-mb-px border-b-2 px-3 py-2 ${tab === t ? "border-brand-600 font-medium text-brand-700" : "border-transparent text-slate-500"}`}>{{ profile: "Extracted profile", text: "Extracted text", versions: `Generated versions (${versions?.length ?? 0})` }[t]}</button>)}
                </div>
                {tab === "profile" && (detail.structured_profile ? <Editor resume={detail} onSaved={reloadDetail} /> : <p className="text-sm text-red-700">{detail.processing_error}</p>)}
                {tab === "text" && <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs">{detail.extracted_text}</pre>}
                {tab === "versions" && (!versions?.length ? <p className="text-sm text-slate-500">No tailored versions yet. They are created per job from the job page.</p> : (
                  <Table><thead><tr><Th>Version</Th><Th>Job</Th><Th>Created</Th><Th>Validation</Th><Th>Approved</Th><Th>Used</Th><Th /></tr></thead>
                    <tbody className="divide-y divide-slate-100">{versions.map((v) => (
                      <tr key={v.id}><Td>v{v.version_number}</Td><Td>{v.job_id ? `#${v.job_id}` : "general"}</Td><Td>{fmtDate(v.created_at)}</Td>
                        <Td>{v.validation_results.passed ? <span className="text-emerald-700">passed</span> : <span className="text-red-700">failed</span>}</Td><Td>{v.approved_at ? fmtDate(v.approved_at) : "—"}</Td><Td>{v.locked ? "yes (locked)" : "no"}</Td>
                        <Td>{v.has_docx && <Button variant="ghost" onClick={() => openSigned(`/api/resume-versions/${v.id}/download-link?fmt=docx`)}>DOCX</Button>}{v.has_pdf && <Button variant="ghost" onClick={() => openSigned(`/api/resume-versions/${v.id}/download-link?fmt=pdf`)}>PDF</Button>}</Td></tr>))}</tbody></Table>))}
              </Card>
            )}
          </div>
        </div>
      )}
    </>
  );
}
