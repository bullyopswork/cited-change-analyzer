// Illustrative test fixture only. Not a regulation, a real source, or a public catalog.
import type { Catalog, Comparison } from '../data';

export const comparison: Comparison = {
  schema_version: '1.0', id: 'illustrative-pair', section: '301-10.1', title: 'Illustrative policy question?', corpus: 'Illustrative test corpus',
  before: { date: '2025-01-01', url: 'https://example.com/earlier', snapshot_sha256: 'illustrative-before', text: 'A 🧭 old amount.' },
  after: { date: '2025-01-02', url: 'https://example.com/later', snapshot_sha256: 'illustrative-after', text: 'A 🧭 new amount.' },
  changes: [
    { id: 'wording-1', category: 'wording', summary: 'Illustrative wording change.', before_evidence: { start: 4, end: 7, quote: 'old' }, after_evidence: { start: 4, end: 7, quote: 'new' }, needs_review: false, review_reason: null, method: 'deterministic' },
    { id: 'review-2', category: 'requirement', summary: 'Illustrative review item.', before_evidence: { start: 8, end: 14, quote: 'amount' }, after_evidence: { start: 8, end: 14, quote: 'amount' }, needs_review: true, review_reason: 'Illustrative review reason.', method: 'deterministic' },
  ],
  warnings: [], analysis: { method: 'deterministic', model: null, latency_ms: 0 },
};
export const catalog: Catalog = {
  schema_version: '1.0', title: 'Cited Change Analyzer', corpus: 'Illustrative test corpus', generated_at: '2025-01-02T00:00:00Z', description: 'Illustrative test archive.',
  comparisons: [{ id: comparison.id, section: comparison.section, title: comparison.title, before_date: comparison.before.date, after_date: comparison.after.date, change_count: 2, categories: ['wording', 'requirement'], path: 'comparisons/illustrative-pair.json', method: 'deterministic' }],
};
