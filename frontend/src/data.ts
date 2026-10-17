export const categories = ['amount', 'date', 'requirement', 'wording', 'added', 'removed', 'editorial', 'moved'] as const;
export type Category = typeof categories[number];
export interface Evidence { start: number; end: number; quote: string }
export interface Snapshot { date: string; url: string; snapshot_sha256: string; text: string; source_kind?: 'local'; filename?: string; format?: 'text' | 'pdf'; pages?: { number: number; start: number; end: number }[]; extraction_warnings?: string[] }
export interface Change {
  id: string;
  category: Category;
  summary: string;
  before_evidence: Evidence | null;
  after_evidence: Evidence | null;
  needs_review: boolean;
  review_reason: string | null;
  method: string;
}
export interface Comparison {
  schema_version: '1.0';
  id: string;
  section: string;
  title: string;
  corpus: string;
  before: Snapshot;
  after: Snapshot;
  changes: Change[];
  warnings: unknown[];
  analysis: Record<string, unknown>;
}
export interface CatalogEntry {
  id: string;
  section: string;
  title: string;
  before_date: string;
  after_date: string;
  change_count: number;
  categories: Category[];
  path: string;
  method: string;
}
export interface Catalog {
  schema_version: '1.0';
  title: string;
  corpus: string;
  generated_at: string;
  description: string;
  comparisons: CatalogEntry[];
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function hasStrings(value: Record<string, unknown>, fields: string[]): boolean {
  return fields.every((field) => typeof value[field] === 'string');
}
function isCategory(value: unknown): value is Category {
  return typeof value === 'string' && categories.includes(value as Category);
}
function uniqueIds(items: { id: string }[]) { return new Set(items.map((item) => item.id)).size === items.length; }
export function safeDataPath(path: string): boolean {
  return path.length > 0 && !path.startsWith('/') && !path.includes('\\') &&
    !/[?#:%]/.test(path) && path.split('/').every((part) => part !== '' && part !== '.' && part !== '..');
}
export function dataUrl(path: string): string {
  if (!safeDataPath(path)) throw new Error('The archive contains an unsupported data path.');
  return `${import.meta.env.BASE_URL}data/${path}`;
}
export function parseCatalog(value: unknown): Catalog {
  if (!isRecord(value) || value.schema_version !== '1.0' ||
      !hasStrings(value, ['title', 'corpus', 'generated_at', 'description']) || !Array.isArray(value.comparisons)) {
    throw new Error('The archive catalog does not match comparison format 1.0.');
  }
  const valid = value.comparisons.every((entry) => isRecord(entry) &&
    hasStrings(entry, ['id', 'section', 'title', 'before_date', 'after_date', 'path', 'method']) &&
    safeDataPath(entry.path as string) && Number.isInteger(entry.change_count) && (entry.change_count as number) >= 0 &&
    Array.isArray(entry.categories) && entry.categories.every(isCategory));
  if (!valid || !uniqueIds(value.comparisons as CatalogEntry[])) throw new Error('The archive has invalid or duplicate comparison entries.');
  return value as unknown as Catalog;
}
function isEvidence(value: unknown): boolean {
  return value === null || (isRecord(value) && Number.isInteger(value.start) && Number.isInteger(value.end) &&
    (value.start as number) >= 0 && (value.end as number) >= (value.start as number) && typeof value.quote === 'string');
}
function isSnapshot(value: unknown): boolean {
  if (!isRecord(value) || !hasStrings(value, ['date', 'url', 'snapshot_sha256', 'text'])) return false;
  if (value.source_kind !== undefined && value.source_kind !== 'local') return false;
  if (value.filename !== undefined && (typeof value.filename !== 'string' || /[\\/]/.test(value.filename))) return false;
  if (value.format !== undefined && value.format !== 'text' && value.format !== 'pdf') return false;
  if (value.extraction_warnings !== undefined && (!Array.isArray(value.extraction_warnings) || !value.extraction_warnings.every((warning) => typeof warning === 'string'))) return false;
  if (value.pages !== undefined && (!Array.isArray(value.pages) || !value.pages.every((page) => isRecord(page) && Number.isInteger(page.number) && (page.number as number) > 0 && Number.isInteger(page.start) && Number.isInteger(page.end) && (page.start as number) >= 0 && (page.end as number) >= (page.start as number) && (page.end as number) <= Array.from(value.text as string).length))) return false;
  return true;
}
export function parseComparison(value: unknown, expected?: CatalogEntry): Comparison {
  if (!isRecord(value) || value.schema_version !== '1.0' || !hasStrings(value, ['id', 'section', 'title', 'corpus']) ||
      !isSnapshot(value.before) || !isSnapshot(value.after) || !Array.isArray(value.changes) ||
      !Array.isArray(value.warnings) || !isRecord(value.analysis)) {
    throw new Error('This comparison does not match format 1.0.');
  }
  const valid = value.changes.every((change) => isRecord(change) && hasStrings(change, ['id', 'summary', 'method']) &&
    isCategory(change.category) && isEvidence(change.before_evidence) && isEvidence(change.after_evidence) &&
    typeof change.needs_review === 'boolean' && (change.review_reason === null || typeof change.review_reason === 'string'));
  if (!valid || !uniqueIds(value.changes as Change[])) throw new Error('This comparison has invalid or duplicate changes.');
  const result = value as unknown as Comparison;
  if (expected && (result.id !== expected.id || result.section !== expected.section ||
      result.before.date !== expected.before_date || result.after.date !== expected.after_date)) {
    throw new Error('This comparison does not match its archive entry.');
  }
  return result;
}
export async function fetchJson(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(dataUrl(path), { signal });
  if (!response.ok) throw new Error(response.status === 404 ? 'This archive file is not available.' : `The archive request failed (${response.status}).`);
  try { return await response.json(); } catch { throw new Error('The archive returned a file that is not valid JSON.'); }
}
export function evidenceMatches(text: string, evidence: Evidence): boolean {
  const points = Array.from(text);
  return Number.isInteger(evidence.start) && Number.isInteger(evidence.end) && evidence.start >= 0 &&
    evidence.end >= evidence.start && evidence.end <= points.length &&
    points.slice(evidence.start, evidence.end).join('') === evidence.quote;
}
export function evidenceParts(text: string, evidence: Evidence): [string, string, string] | null {
  if (!evidenceMatches(text, evidence)) return null;
  const points = Array.from(text);
  return [points.slice(0, evidence.start).join(''), points.slice(evidence.start, evidence.end).join(''), points.slice(evidence.end).join('')];
}
export function sourceUrl(value: string): string | undefined {
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined; } catch { return undefined; }
}
export function friendlyDate(value: string): string {
  const date = new Date(`${value}T12:00:00Z`);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' }).format(date);
}
export function displayValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? 'Not provided';
}
