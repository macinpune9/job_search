"use client";
import { useEffect, useState } from "react";
import { ApiError, api, fmtDate, useApi } from "@/lib/api";
import { Button, Card, Chip, ErrorBox, Field, Input, Loading, Notice, PageHeader, Select, Textarea, useToast } from "@/components/ui";

const EMPLOYMENT = [["permanent", "Permanent / full-time"], ["part_time", "Part-time"], ["fixed_term", "Fixed-term contract"], ["temporary", "Temporary contract"], ["freelance", "Freelance / contractor"], ["contract_to_hire", "Contract-to-hire"], ["internship", "Internship"]];
const MODES = [["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]];
const KINDS = ["title", "skill", "tool", "certification", "industry", "seniority", "other"];
const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

const blank = () => ({
  profile_name: "My search", keywords: [] as any[], match_mode: "weighted", exclusions: {} as any, employment_types: [] as string[],
  role_preferences: {} as any, salary_preferences: { currency: "USD", period: "year", basis: "gross" } as any, location_preferences: {} as any,
  remote_preferences: [] as string[], other_filters: {} as any, sources: [] as any[], resume_id: null as number | null,
  date_lookback_days: 30, unknown_date_policy: "include", min_match_score: 40, overlap_hours: 48, active: true,
});

export default function Preferences() {
  const { data: list, reload: reloadList, loading } = useApi<any[]>("/api/search-profiles");
  const { data: resumes } = useApi<any[]>("/api/resumes");
  const [sel, setSel] = useState<number | "new" | null>(null);
  const [f, setF] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [run, setRun] = useState<any>(null);
  const [newKw, setNewKw] = useState("");
  const [src, setSrc] = useState({ source: "greenhouse", board: "" });
  const { toast, node } = useToast();

  useEffect(() => { if (list && sel === null) setSel(list[0]?.id ?? "new"); }, [list, sel]);
  useEffect(() => {
    if (sel === "new") setF(blank());
    else if (sel && list) setF(list.find((p) => p.id === sel) || null);
    setPreview(null); setRun(null); setErr(null);
  }, [sel, list]);
  if (loading || !f) return <Loading />;
  const set = (k: string, v: any) => setF({ ...f, [k]: v });
  const nest = (k: string, kk: string, v: any) => setF({ ...f, [k]: { ...f[k], [kk]: v } });
  const toggle = (k: string, v: string) => set(k, f[k].includes(v) ? f[k].filter((x: string) => x !== v) : [...f[k], v]);
  const setKw = (i: number, patch: any) => set("keywords", f.keywords.map((k: any, j: number) => (j === i ? { ...k, ...patch } : k)));

  async function save() {
    setBusy("save"); setErr(null);
    try {
      const body = { ...f, salary_preferences: cleanSalary(f.salary_preferences) };
      const saved = sel === "new" ? await api("/api/search-profiles", { body }) : await api(`/api/search-profiles/${sel}`, { method: "PATCH", body });
      toast("Saved"); await reloadList(); setSel(saved.id);
    } catch (e: any) { setErr(e.message); } finally { setBusy(""); }
  }
  const cleanSalary = (s: any) => { const o = { ...s }; for (const k of ["min", "target", "max"]) if (o[k] === "" || o[k] == null || Number.isNaN(o[k])) delete o[k]; return o; };

  async function suggest() {
    const rid = f.resume_id || resumes?.find((r) => r.processing_status === "parsed")?.id;
    if (!rid) return setErr("Upload a resume first.");
    try {
      const r = await api(`/api/keywords/suggest?resume_id=${rid}`);
      const have = new Set(f.keywords.map((k: any) => k.term.toLowerCase()));
      set("keywords", [...f.keywords, ...r.keywords.filter((k: any) => !have.has(k.term.toLowerCase())).map(({ source, ...k }: any) => k)]);
      toast(`Added ${r.keywords.length} suggestions. Edit or remove any of them.`);
    } catch (e: any) { setErr(e.message); }
  }
  async function doPreview() {
    if (sel === "new") return toast("Save the profile first", "err");
    setBusy("prev");
    try { setPreview(await api(`/api/search-profiles/${sel}/keyword-preview`, { body: { keywords: f.keywords, match_mode: f.match_mode, exclusions: f.exclusions } })); }
    catch (e: any) { setErr(e.message); } finally { setBusy(""); }
  }
  async function runNow() {
    setBusy("run"); setRun({ status: "running" });
    try {
      await api(`/api/search-profiles/${sel}`, { method: "PATCH", body: { ...f, salary_preferences: cleanSalary(f.salary_preferences) } });
      const t = await api(`/api/search-profiles/${sel}/run`, { method: "POST" });
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        const r = await api(t.poll);
        setRun(r);
        if (r.status !== "running") break;
      }
    } catch (e: any) { setRun(null); setErr(e instanceof ApiError ? e.message : "Run failed"); } finally { setBusy(""); }
  }

  return (
    <>
      {node}
      <PageHeader title="Job Search Preferences" subtitle="Hard filters exclude jobs; everything else only influences the match score. You can keep several named search profiles."
        actions={<><Select aria-label="Search profile" value={String(sel)} onChange={(e) => setSel(e.target.value === "new" ? "new" : +e.target.value)} className="w-auto">
          {(list || []).map((p) => <option key={p.id} value={p.id}>{p.profile_name}</option>)}<option value="new">+ New profile</option></Select></>} />
      <ErrorBox message={err} />
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Profile">
          <div className="space-y-3">
            <Field label="Profile name"><Input value={f.profile_name} onChange={(e) => set("profile_name", e.target.value)} /></Field>
            <Field label="Resume used for matching"><Select value={f.resume_id ?? ""} onChange={(e) => set("resume_id", e.target.value ? +e.target.value : null)}><option value="">Primary resume</option>{(resumes || []).map((r) => <option key={r.id} value={r.id}>{r.label || r.filename}</option>)}</Select></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="First search looks back (days)" hint="Jobs posted within this window. Default 30."><Input type="number" min={1} max={365} value={f.date_lookback_days} onChange={(e) => set("date_lookback_days", +e.target.value)} /></Field>
              <Field label="If posted date is unknown" hint="Modified dates are never treated as posted dates."><Select value={f.unknown_date_policy} onChange={(e) => set("unknown_date_policy", e.target.value)}><option value="include">Include (flagged)</option><option value="exclude">Exclude</option></Select></Field>
              <Field label="Minimum match score"><Input type="number" min={0} max={100} value={f.min_match_score} onChange={(e) => set("min_match_score", +e.target.value)} /></Field>
              <label className="flex items-end gap-2 pb-2 text-sm"><input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} /> Active (included in scheduled runs)</label>
            </div>
          </div>
        </Card>
        <Card title="Job sources">
          <div className="space-y-3">
            <Notice>Only the sources you add here are searched. Enter a company&apos;s public job-board name (for example Greenhouse board “gitlab”, Lever site “spotify”, Ashby board “ramp”).</Notice>
            <div className="flex flex-wrap gap-1">{f.sources.map((s: any, i: number) => <Chip key={i} onRemove={() => set("sources", f.sources.filter((_: any, j: number) => j !== i))}>{s.source}:{s.board}</Chip>)}{f.sources.length === 0 && <span className="text-sm text-amber-700">No sources yet; a run will fail until you add one.</span>}</div>
            <div className="flex gap-2">
              <Select aria-label="Source type" value={src.source} onChange={(e) => setSrc({ ...src, source: e.target.value })} className="w-36"><option value="greenhouse">Greenhouse</option><option value="lever">Lever</option><option value="ashby">Ashby</option></Select>
              <Input aria-label="Board name" placeholder="board name" value={src.board} onChange={(e) => setSrc({ ...src, board: e.target.value })} />
              <Button variant="secondary" onClick={() => { if (/^[A-Za-z0-9._-]+$/.test(src.board)) { set("sources", [...f.sources, src]); setSrc({ ...src, board: "" }); } else toast("Board names use letters, digits, . _ -", "err"); }}>Add</Button>
            </div>
          </div>
        </Card>
        <Card title="Keywords" className="xl:col-span-2" actions={<><Button variant="secondary" onClick={suggest}>Suggest from my resume</Button><Select aria-label="Match mode" value={f.match_mode} onChange={(e) => set("match_mode", e.target.value)} className="w-auto"><option value="weighted">Weighted</option><option value="or">Any keyword (OR)</option><option value="and">All keywords (AND)</option></Select></>}>
          <div className="space-y-3">
            <p className="text-sm text-slate-500">Mark a keyword <b>required</b> only if a job must contain it. <b>Exclude</b> removes jobs that mention it. Everything else just raises the score.</p>
            <div className="space-y-2">
              {f.keywords.map((k: any, i: number) => (
                <div key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 p-2">
                  <Input aria-label="Keyword" value={k.term} onChange={(e) => setKw(i, { term: e.target.value })} className="w-48" />
                  <Select aria-label="Kind" value={k.kind} onChange={(e) => setKw(i, { kind: e.target.value })} className="w-32">{KINDS.map((x) => <option key={x}>{x}</option>)}</Select>
                  <Input aria-label="Synonyms" placeholder="synonyms, comma separated" value={(k.synonyms || []).join(", ")} onChange={(e) => setKw(i, { synonyms: csv(e.target.value) })} className="w-56" />
                  <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!k.required} disabled={k.excluded} onChange={(e) => setKw(i, { required: e.target.checked })} /> required</label>
                  <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={!!k.excluded} onChange={(e) => setKw(i, { excluded: e.target.checked, required: false })} /> exclude</label>
                  <Button variant="ghost" aria-label={`Remove ${k.term}`} onClick={() => set("keywords", f.keywords.filter((_: any, j: number) => j !== i))}>Remove</Button>
                </div>
              ))}
              {f.keywords.length === 0 && <p className="text-sm text-slate-400">No keywords yet.</p>}
            </div>
            <div className="flex gap-2"><Input placeholder="Add a keyword" value={newKw} onChange={(e) => setNewKw(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && newKw.trim()) { set("keywords", [...f.keywords, { term: newKw.trim(), kind: "skill", required: false, excluded: false, synonyms: [], weight: 1 }]); setNewKw(""); } }} className="max-w-xs" />
              <Button variant="secondary" onClick={() => { if (newKw.trim()) { set("keywords", [...f.keywords, { term: newKw.trim(), kind: "skill", required: false, excluded: false, synonyms: [], weight: 1 }]); setNewKw(""); } }}>Add</Button>
              <Button variant="secondary" busy={busy === "prev"} onClick={doPreview}>Preview effect</Button></div>
            {preview && <Notice>Against {preview.jobs_evaluated} jobs already discovered, these settings would keep <b>{preview.would_qualify}</b>. Required: {preview.explanation.required.join(", ") || "none"} · Excluded: {preview.explanation.excluded.join(", ") || "none"} · Optional: {preview.explanation.optional.length}. Exclusion reasons: {Object.entries(preview.exclusion_reasons).map(([k, n]) => `${k.replace(/_/g, " ")} (${n})`).join(", ") || "none"}.</Notice>}
          </div>
        </Card>
        <Card title="Role & employment">
          <div className="space-y-3">
            <Field label="Target job titles" hint="Comma separated"><Input value={(f.role_preferences.target_titles || []).join(", ")} onChange={(e) => nest("role_preferences", "target_titles", csv(e.target.value))} /></Field>
            <Field label="Alternative titles"><Input value={(f.role_preferences.alternative_titles || []).join(", ")} onChange={(e) => nest("role_preferences", "alternative_titles", csv(e.target.value))} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Seniority"><Select value={f.role_preferences.seniority || ""} onChange={(e) => nest("role_preferences", "seniority", e.target.value)}><option value="">Any</option>{["junior", "mid", "senior", "staff", "lead", "principal", "manager", "director"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
              <Field label="Job function"><Input value={f.role_preferences.function || ""} onChange={(e) => nest("role_preferences", "function", e.target.value)} /></Field>
            </div>
            <fieldset><legend className="mb-1 text-sm font-medium text-slate-700">Employment types (none selected = any)</legend>
              <div className="grid grid-cols-2 gap-1">{EMPLOYMENT.map(([v, l]) => <label key={v} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.employment_types.includes(v)} onChange={() => toggle("employment_types", v)} />{l}</label>)}</div></fieldset>
            <fieldset><legend className="mb-1 text-sm font-medium text-slate-700">Work mode (hard filter when job states it)</legend>
              <div className="flex gap-4">{MODES.map(([v, l]) => <label key={v} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.remote_preferences.includes(v)} onChange={() => toggle("remote_preferences", v)} />{l}</label>)}</div></fieldset>
          </div>
        </Card>
        <Card title="Compensation & location">
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <Field label="Minimum"><Input type="number" value={f.salary_preferences.min ?? ""} onChange={(e) => nest("salary_preferences", "min", e.target.value === "" ? "" : +e.target.value)} /></Field>
              <Field label="Target"><Input type="number" value={f.salary_preferences.target ?? ""} onChange={(e) => nest("salary_preferences", "target", e.target.value === "" ? "" : +e.target.value)} /></Field>
              <Field label="Maximum (optional)"><Input type="number" value={f.salary_preferences.max ?? ""} onChange={(e) => nest("salary_preferences", "max", e.target.value === "" ? "" : +e.target.value)} /></Field>
              <Field label="Currency"><Input maxLength={3} value={f.salary_preferences.currency || ""} onChange={(e) => nest("salary_preferences", "currency", e.target.value.toUpperCase())} /></Field>
              <Field label="Period"><Select value={f.salary_preferences.period || "year"} onChange={(e) => nest("salary_preferences", "period", e.target.value)}>{["year", "month", "week", "day", "hour"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
              <Field label="Basis"><Select value={f.salary_preferences.basis || "gross"} onChange={(e) => nest("salary_preferences", "basis", e.target.value)}><option>gross</option><option>net</option></Select></Field>
            </div>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.salary_preferences.negotiable} onChange={(e) => nest("salary_preferences", "negotiable", e.target.checked)} /> Negotiable</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.salary_preferences.strict} onChange={(e) => nest("salary_preferences", "strict", e.target.checked)} /> Exclude jobs paying less (only when currency, period and basis are comparable)</label>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Country"><Input value={f.location_preferences.country || ""} onChange={(e) => nest("location_preferences", "country", e.target.value)} /></Field>
              <Field label="State / region"><Input value={f.location_preferences.region || ""} onChange={(e) => nest("location_preferences", "region", e.target.value)} /></Field>
              <Field label="City"><Input value={f.location_preferences.city || ""} onChange={(e) => nest("location_preferences", "city", e.target.value)} /></Field>
              <Field label="Postal code"><Input value={f.location_preferences.postal_code || ""} onChange={(e) => nest("location_preferences", "postal_code", e.target.value)} /></Field>
              <Field label="Search radius"><div className="flex gap-1"><Input type="number" value={f.location_preferences.radius || ""} onChange={(e) => nest("location_preferences", "radius", +e.target.value)} /><Select value={f.location_preferences.unit || "km"} onChange={(e) => nest("location_preferences", "unit", e.target.value)} className="w-20"><option>km</option><option>mi</option></Select></div></Field>
              <Field label="Languages"><Input value={(f.other_filters.languages || []).join(", ")} onChange={(e) => nest("other_filters", "languages", csv(e.target.value))} /></Field>
            </div>
            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.location_preferences.strict} onChange={(e) => nest("location_preferences", "strict", e.target.checked)} /> Location is a hard filter</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.location_preferences.relocate} onChange={(e) => nest("location_preferences", "relocate", e.target.checked)} /> Willing to relocate</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={!!f.location_preferences.travel} onChange={(e) => nest("location_preferences", "travel", e.target.checked)} /> Willing to travel</label>
            </div>
          </div>
        </Card>
        <Card title="Exclusions (hard filters)" className="xl:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[["companies", "Excluded companies"], ["industries", "Excluded industries"], ["roles", "Excluded roles"], ["keywords", "Excluded words"]].map(([k, l]) => (
              <Field key={k} label={l} hint="Comma separated"><Textarea rows={2} value={(f.exclusions[k] || []).join(", ")} onChange={(e) => nest("exclusions", k, csv(e.target.value))} /></Field>
            ))}
          </div>
        </Card>
      </div>
      <div className="sticky bottom-0 mt-4 flex flex-wrap items-center gap-3 border-t border-slate-200 bg-slate-50/95 py-3 backdrop-blur">
        <Button busy={busy === "save"} onClick={save}>Save profile</Button>
        {sel !== "new" && <Button variant="secondary" busy={busy === "run"} onClick={runNow}>Save first, then run search now</Button>}
        {run && <span className="text-sm text-slate-600">{run.status === "running" ? "Searching sources…" : <>Run {run.status}: {run.stats?.new_jobs ?? 0} new, {run.stats?.qualified_new ?? 0} matching{run.error_summary ? ` · ${run.error_summary}` : ""} ({fmtDate(run.completed_at)})</>}</span>}
      </div>
    </>
  );
}
