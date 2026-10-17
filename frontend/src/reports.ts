import { type Comparison, type Snapshot, displayValue, sourceUrl } from './data';

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]!);
}
function link(url: string): string {
  const safe = sourceUrl(url);
  return safe ? `<a href="${escapeHtml(safe)}" rel="noopener noreferrer">Dated source</a>` : 'Source link unavailable';
}
function sourceLabel(snapshot: Snapshot): string {
  return snapshot.source_kind === 'local' ? snapshot.filename || 'Local document' : snapshot.date;
}
function sourceDetails(snapshot: Snapshot): string {
  if (snapshot.source_kind !== 'local') return link(snapshot.url);
  return `Local ${escapeHtml(snapshot.format || 'document')} file · Imported ${escapeHtml(snapshot.date)}${snapshot.pages ? ` · ${snapshot.pages.length} pages` : ''}${snapshot.extraction_warnings?.length ? `<br>${snapshot.extraction_warnings.map(escapeHtml).join('<br>')}` : ''}`;
}
export function htmlReport(comparison: Comparison): string {
  const e = escapeHtml;
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${e(comparison.section)} comparison</title>
<style>body{max-width:75rem;margin:3rem auto;padding:0 1.5rem;font:16px/1.65 system-ui;color:#182a2d;background:#faf9f5}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:white;padding:1.5rem;border:1px solid #ddd}article{border-top:1px solid #ccc;padding:1rem 0}small{color:#4c5d60}</style>
<h1>Cited Change Analyzer</h1><p>${comparison.before.source_kind === 'local' ? 'Local document report.' : 'Precomputed archive report.'} Evidence is linked to source text. Citation matching does not verify the explanation or establish legal effect.</p>
<h2>${comparison.before.source_kind === 'local' ? 'Document comparison' : `§ ${e(comparison.section)}: ${e(comparison.title)}`}</h2><p>${e(comparison.corpus)} · ${e(sourceLabel(comparison.before))} to ${e(sourceLabel(comparison.after))}</p>
<h2>Changes (${comparison.changes.length})</h2>${comparison.changes.length === 0 ? '<p>No changes recorded for this pair.</p>' : comparison.changes.map((change, index) => `<article><h3>${index + 1}. ${e(change.summary)}</h3><p>${e(change.category)} · Method: ${e(change.method)}${change.needs_review ? ' · Needs review' : ''}</p>${change.review_reason ? `<p>${e(change.review_reason)}</p>` : ''}<p>Earlier evidence: ${change.before_evidence ? e(change.before_evidence.quote) : 'No passage on this side.'}</p><p>Later evidence: ${change.after_evidence ? e(change.after_evidence.quote) : 'No passage on this side.'}</p></article>`).join('')}
${(['before', 'after'] as const).map((side) => `<h2>${side === 'before' ? 'Earlier' : 'Later'} text: ${e(sourceLabel(comparison[side]))}</h2><p>${sourceDetails(comparison[side])}</p><pre>${e(comparison[side].text || 'Section absent from this snapshot.')}</pre><small>Snapshot SHA256: ${e(comparison[side].snapshot_sha256)}</small>`).join('')}
<h2>Analysis record</h2><pre>${e(displayValue(comparison.analysis))}</pre><h2>Warnings</h2><pre>${e(comparison.warnings.length ? displayValue(comparison.warnings) : 'No warnings recorded.')}</pre></html>`;
}
export function downloadReport(comparison: Comparison, format: 'json' | 'html'): void {
  const body = format === 'json' ? JSON.stringify(comparison, null, 2) : htmlReport(comparison);
  const blob = new Blob([body], { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `${comparison.id.replace(/[^a-zA-Z0-9._-]/g, '_')}.${format}`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
