/**
 * Defanging of untrusted links (SECURITY U6). Untrusted text (scam messages, user input, web snippets, model
 * output) is shown as inert text: URLs are rewritten so they are neither clickable nor auto-linked by the
 * browser or by chat/email clients when copied:
 *   https://evil.example/a?b=1  ->  hxxps://evil[.]example/a?b=1
 * The product never turns these into <a> elements and never fetches them.
 */
const URL_RE = /\b(?:https?:\/\/|ftp:\/\/|www\.)[^\s<>"'`]+/gi;
const BARE_DOMAIN_RE = /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|co|in|info|biz|xyz|top|click|link|ru|cn|tk|ml|ga|cf|gq|app|dev|me|ly|cc|site|online|live|shop|support|help|bank)\b(?:\/[^\s<>"'`]*)?/gi;

export function defangUrl(raw: string): string {
  let s = raw.replace(/^https?/i, (m) => m.replace(/^http/i, "hxxp")).replace(/^ftp/i, "fxp");
  // Defang only the host part (up to first / ? #), keep the path readable.
  const m = /^((?:hxxps?:\/\/|fxp:\/\/)?)([^/?#]*)(.*)$/i.exec(s);
  if (m) s = `${m[1]}${(m[2] ?? "").replace(/\./g, "[.]")}${m[3] ?? ""}`;
  return s.replace(/@/g, "[@]");
}

export type TextSegment = { kind: "text"; text: string } | { kind: "link"; text: string; defanged: string };

/** Split text into plain segments and defanged-URL segments. Pure; no DOM. */
export function segmentUntrusted(text: string): TextSegment[] {
  const hits: { start: number; end: number }[] = [];
  for (const re of [URL_RE, BARE_DOMAIN_RE]) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      const start = m.index;
      const end = start + m[0].length;
      if (!hits.some((h) => start < h.end && end > h.start)) hits.push({ start, end });
      if (m[0].length === 0) re.lastIndex++;
    }
  }
  hits.sort((a, b) => a.start - b.start);
  const out: TextSegment[] = [];
  let pos = 0;
  for (const h of hits) {
    if (h.start > pos) out.push({ kind: "text", text: text.slice(pos, h.start) });
    // Trailing sentence punctuation is not part of the URL.
    let slice = text.slice(h.start, h.end);
    const trail = /[.,;:!?)\]]+$/.exec(slice)?.[0] ?? "";
    slice = slice.slice(0, slice.length - trail.length);
    out.push({ kind: "link", text: slice, defanged: defangUrl(slice) });
    if (trail) out.push({ kind: "text", text: trail });
    pos = h.end;
  }
  if (pos < text.length) out.push({ kind: "text", text: text.slice(pos) });
  return out;
}
