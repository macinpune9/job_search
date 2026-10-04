"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { Button, Card, ErrorBox, Input, Loading, Notice, Select, useToast } from "@/components/ui";

type Item = { name: string; checked: boolean; proficiency?: string; evidence?: string };
const LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"];

const toItems = (xs: any[] = [], checked = true): Item[] => xs.map((x) => ({ name: x.name, checked, proficiency: x.proficiency, evidence: x.evidence }));

function Group({ title, hint, items, setItems, extras, withLevel, addLabel }: {
  title: string; hint: string; items: Item[]; setItems: (v: Item[]) => void; extras?: Item[]; withLevel?: boolean; addLabel: string;
}) {
  const [more, setMore] = useState(false);
  const [draft, setDraft] = useState("");
  const shown = more ? [...items, ...(extras || []).filter((e) => !items.some((i) => i.name === e.name))] : items;
  const update = (name: string, patch: Partial<Item>) => {
    const exists = items.some((i) => i.name === name);
    setItems(exists ? items.map((i) => (i.name === name ? { ...i, ...patch } : i)) : [...items, { ...(extras || []).find((e) => e.name === name)!, ...patch }]);
  };
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between"><h3 className="text-sm font-semibold text-slate-800">{title}</h3><span className="text-xs text-slate-500">{hint}</span></div>
      <ul className="space-y-1.5">
        {shown.map((it) => (
          <li key={it.name} className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 px-3 py-2">
            <label className="flex flex-1 items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={items.some((i) => i.name === it.name && i.checked)} onChange={(e) => update(it.name, { checked: e.target.checked })} />
              <span><span className="font-medium">{it.name}</span>{it.evidence && <span className="block text-xs text-slate-500">{it.evidence}</span>}</span>
            </label>
            {withLevel && (
              <Select aria-label={`${it.name} proficiency`} value={items.find((i) => i.name === it.name)?.proficiency || it.proficiency || "Intermediate"} onChange={(e) => update(it.name, { proficiency: e.target.value })} className="w-36">
                {LEVELS.map((l) => <option key={l}>{l}</option>)}
              </Select>)}
          </li>
        ))}
        {shown.length === 0 && <li className="text-sm text-slate-400">Nothing found: add your own below.</li>}
      </ul>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Input aria-label={addLabel} placeholder={addLabel} value={draft} onChange={(e) => setDraft(e.target.value)} className="max-w-xs"
          onKeyDown={(e) => { if (e.key === "Enter" && draft.trim()) { setItems([...items, { name: draft.trim(), checked: true, proficiency: "Intermediate" }]); setDraft(""); } }} />
        <Button variant="secondary" onClick={() => { if (draft.trim()) { setItems([...items, { name: draft.trim(), checked: true, proficiency: "Intermediate" }]); setDraft(""); } }}>Add</Button>
        {(extras || []).length > 0 && <button type="button" className="text-sm text-brand-600 underline" onClick={() => setMore(!more)}>{more ? "Show fewer" : `Show ${extras!.length} more suggestions`}</button>}
      </div>
    </div>
  );
}

export default function CareerSnapshot({ resumeId }: { resumeId: number }) {
  const [ai, setAi] = useState(false);
  const [nonce, setNonce] = useState(0);
  const { data: s, error, loading } = useApi<any>(`/api/resumes/${resumeId}/insights?ai=${ai}${nonce ? "&refresh=true" : ""}`, [nonce]);
  const [roles, setRoles] = useState<Item[]>([]);
  const [tech, setTech] = useState<Item[]>([]);
  const [beh, setBeh] = useState<Item[]>([]);
  const [tools, setTools] = useState<Item[]>([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<any>(null);
  const { toast, node } = useToast();

  useEffect(() => {
    if (!s) return;
    setRoles((s.roles || []).map((r: any) => ({ name: r.title, checked: true, evidence: r.reason })));
    setTech(toItems(s.technical_skills)); setBeh(toItems(s.behavioural_skills)); setTools(toItems(s.tools)); setDone(null);
  }, [s]);

  const ex = (k: string) => toItems(s?.extras?.[k], false);
  const picked = (xs: Item[]) => xs.filter((x) => x.checked);
  const apply = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api("/api/insights/apply", { body: {
        resume_id: resumeId, roles: picked(roles).map((x) => x.name), technical: picked(tech).map((x) => x.name),
        behavioural: picked(beh).map((x) => x.name), tools: picked(tools).map((x) => ({ name: x.name, proficiency: x.proficiency || "Intermediate" })) } });
      setDone(r); toast(r.created ? "Search profile created" : "Search profile updated");
    } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }, [roles, tech, beh, tools, resumeId, toast]);

  if (loading && !s) return <Loading />;
  if (error || !s) return <ErrorBox message={error} />;
  return (
    <div className="space-y-5">
      {node}
      <div className="rounded-xl bg-brand-50 p-4 text-sm text-slate-700">
        <b>Here is what stands out on your CV.</b> Untick anything that is wrong, then press the button at the bottom: it fills in your search for you. A job does not need to match everything; jobs that fit roughly {" "}
        <b>40–50%</b> of this are shown too.
        <div className="mt-1 text-xs text-slate-500">
          Based on ~{s.total_years} years of experience · {s.ignored_items > 0 ? `${s.ignored_items} items that are not skills (school, places, hobbies, languages…) were ignored · ` : ""}
          {s.source === "ai" ? "AI-assisted (every item is backed by a quote from your CV)" : "rule-based"}{s.used_linkedin ? " · includes your LinkedIn text" : ""}
        </div>
      </div>
      {s.ai_error && <Notice tone="warn">{s.ai_error}</Notice>}
      {s.source === "rules" && s.ai_available && !s.ai_enabled && <Notice>Want smarter picks (and a better reading of unusual CV layouts)? Turn on AI in <Link className="underline" href="/automation">Automation Settings</Link>.</Notice>}
      {s.linkedin_missing && <Notice>Add your LinkedIn text in <Link className="underline" href="/profile">My Profile</Link> for better suggestions. LinkedIn cannot be read automatically, so you paste it once.</Notice>}
      {s.ai_enabled && s.source !== "ai" && <Button variant="secondary" onClick={() => { setAi(true); setNonce(nonce + 1); }}>Improve with AI</Button>}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="1 · Roles to search for"><Group title="Best-fit roles" hint="pick 1–3" items={roles} setItems={setRoles} addLabel="Add another role" /></Card>
        <Card title="2 · Behavioural skills"><Group title="Shown by your achievements" hint="2–3 is plenty" items={beh} setItems={setBeh} extras={ex("behavioural")} addLabel="Add a skill" /></Card>
        <Card title="3 · Technical skills"><Group title="Your strongest" hint="up to 5" items={tech} setItems={setTech} extras={ex("technical")} addLabel="Add a skill" /></Card>
        <Card title="4 · Tools and proficiency"><Group title="Tools you use most" hint="levels are estimates: adjust" items={tools} setItems={setTools} extras={ex("tools")} withLevel addLabel="Add a tool" /></Card>
      </div>

      <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-3 border-t border-slate-200 bg-slate-50/95 px-1 py-3 backdrop-blur">
        <Button busy={busy} disabled={picked(roles).length === 0} onClick={apply}>Use these for my job search</Button>
        {done ? <span className="text-sm text-emerald-700">Saved ({done.profile.keywords.length} keywords, none required). <Link className="font-medium underline" href="/preferences">Next: add job sources and run your search →</Link></span>
          : <span className="text-xs text-slate-500">You can still change everything later in Job Search Preferences.</span>}
      </div>
    </div>
  );
}
