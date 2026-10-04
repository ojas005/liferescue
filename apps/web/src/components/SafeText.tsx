"use client";

import { useState } from "react";
import { segmentUntrusted } from "@/lib/safe-text";

/**
 * Renders untrusted text as inert text (SECURITY U6):
 *  - React escapes it; there is no dangerouslySetInnerHTML and no markdown/HTML rendering, so no images or
 *    remote content can load;
 *  - URLs are DEFANGED (hxxps://example[.]com) and never become links; each gets a "Copy" button that copies
 *    the defanged form;
 *  - displayed length is capped so huge payloads cannot freeze the page.
 */
const MAX_CHARS = 4000;

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="ml-1 rounded border border-slate-300 bg-white px-1 py-0 align-baseline text-[10px] font-medium text-slate-600 hover:bg-slate-100"
      aria-label="Copy defanged link"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function SafeText({ text, className = "", defang = true }: { text: string; className?: string; defang?: boolean }) {
  const clipped = text.length > MAX_CHARS;
  const shown = clipped ? text.slice(0, MAX_CHARS) : text;
  const segments = defang ? segmentUntrusted(shown) : [{ kind: "text" as const, text: shown }];
  return (
    <span className={`whitespace-pre-wrap break-words [overflow-wrap:anywhere] ${className}`}>
      {segments.map((s, i) =>
        s.kind === "text" ? (
          <span key={i}>{s.text}</span>
        ) : (
          <span key={i} data-testid="defanged-link" className="rounded bg-amber-50 px-0.5 font-mono text-[0.92em] text-amber-950">
            {s.defanged}
            <CopyButton value={s.defanged} />
          </span>
        ),
      )}
      {clipped ? <span className="text-slate-500"> ... [{text.length - MAX_CHARS} more characters not shown]</span> : null}
    </span>
  );
}
