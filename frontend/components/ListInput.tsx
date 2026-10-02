"use client";
import { useEffect, useRef, useState } from "react";
import { Input, Textarea } from "@/components/ui";

/**
 * Edits a list of strings as text ("a, b, c" or one per line).
 * The raw text is kept while you type (so spaces, commas and new lines are never swallowed) and is only
 * normalised when the field loses focus. The parsed list is reported on every change.
 */
export default function ListInput({ value, onChange, mode = "csv", multiline = false, ...rest }: {
  value: string[]; onChange: (v: string[]) => void; mode?: "csv" | "lines"; multiline?: boolean;
} & Omit<React.InputHTMLAttributes<HTMLInputElement> & React.TextareaHTMLAttributes<HTMLTextAreaElement>, "value" | "onChange">) {
  const sep = mode === "csv" ? ", " : "\n";
  const parse = (t: string) => t.split(mode === "csv" ? "," : "\n").map((s) => s.trim()).filter(Boolean);
  const [text, setText] = useState(value.join(sep));
  const focused = useRef(false);
  const key = value.join("\u0001");
  useEffect(() => { if (!focused.current) setText(value.join(sep)); }, [key, sep]); // eslint-disable-line react-hooks/exhaustive-deps (external changes only)
  const props = {
    ...rest,
    value: text,
    onFocus: () => { focused.current = true; },
    onBlur: () => { focused.current = false; setText(parse(text).join(sep)); },
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => { setText(e.target.value); onChange(parse(e.target.value)); },
  };
  return multiline ? <Textarea {...(props as any)} /> : <Input {...(props as any)} />;
}
