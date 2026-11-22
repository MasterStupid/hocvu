import type { ReactNode } from 'react';

const URL_RE = /(https?:\/\/[^\s<>]+)/g;

function renderLinks(text: string, key: string): ReactNode[] {
  const parts = text.split(URL_RE);
  const out: ReactNode[] = [];
  parts.forEach((part, idx) => {
    if (!part) return;
    if (idx % 2 === 1) {
      // Strip trailing sentence punctuation that is not part of the URL.
      const match = /^(https?:\/\/[^\s<>]+?)([.,;:!?)\]]*)$/.exec(part);
      const href = match ? match[1] : part;
      const trailing = match ? match[2] : '';
      let safeHref = '';
      try {
        const parsed = new URL(href);
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') safeHref = parsed.href;
      } catch { /* invalid url */ }
      if (safeHref) {
        out.push(
          <a
            key={`${key}-u${idx}`}
            href={safeHref}
            target="_blank"
            rel="noopener noreferrer"
            className="underline decoration-seal/60 underline-offset-2 text-seal hover:text-seal/80 break-all"
          >
            {href}
          </a>,
        );
        if (trailing) out.push(<span key={`${key}-t${idx}`}>{trailing}</span>);
        return;
      }
    }
    out.push(<span key={`${key}-s${idx}`}>{part}</span>);
  });
  return out;
}

// Safe renderer: text nodes only; recognises lists, pipe tables, safe http(s) URLs, and **bold**.
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, i) =>
    part.startsWith('**') && part.endsWith('**')
      ? <strong key={`${key}-${i}`}>{renderLinks(part.slice(2, -2), `${key}-b${i}`)}</strong>
      : <span key={`${key}-${i}`}>{renderLinks(part, `${key}-p${i}`)}</span>,
  );
}
const cells = (line: string) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
const isDivider = (line = '') => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line);
const ITEM = /^\s*(?:([-•*+])|(\d+)[.)])\s+(.*)$/;

export function RichText({ text, tail }: { text: string; tail?: ReactNode }) {
  const lines = String(text || '').split('\n');
  const blocks: { kind: 'p' | 'other'; node: ReactNode }[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    if (line.includes('|') && isDivider(lines[i + 1])) {
      const head = cells(line); const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
      const k = `t${i}`;
      blocks.push({ kind: 'other', node: (
        <div key={k} className="overflow-x-auto my-2 scroll-thin"><table>
          <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `${k}h${j}`)}</th>)}</tr></thead>
          <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, `${k}${ri}-${j}`)}</td>)}</tr>)}</tbody>
        </table></div>
      ) });
      continue;
    }
    const item = line.match(ITEM);
    if (item) {
      const ordered = Boolean(item[2]); const start = ordered ? Number(item[2]) : 1; const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(ITEM);
        if (!m || Boolean(m[2]) !== ordered) break;
        items.push(m[3]); i++;
      }
      const k = `l${i}`;
      const lis = items.map((t, j) => <li key={j}>{inline(t, `${k}-${j}`)}</li>);
      blocks.push({ kind: 'other', node: ordered ? <ol key={k} start={start}>{lis}</ol> : <ul key={k}>{lis}</ul> });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !ITEM.test(lines[i]) && !(lines[i].includes('|') && isDivider(lines[i + 1]))) para.push(lines[i++]);
    const k = `p${i}`;
    blocks.push({ kind: 'p', node: para.map((p, j) => <span key={j}>{j > 0 && <br />}{inline(p, `${k}-${j}`)}</span>) });
  }
  if (!blocks.length) blocks.push({ kind: 'p', node: null });
  const last = blocks.length - 1;
  return (
    <div className="rich">
      {blocks.map((b, idx) => b.kind === 'p'
        ? <p key={idx}>{b.node}{idx === last && tail ? <> {tail}</> : null}</p>
        : <div key={idx}>{b.node}</div>)}
      {blocks[last].kind !== 'p' && tail ? <p>{tail}</p> : null}
    </div>
  );
}
