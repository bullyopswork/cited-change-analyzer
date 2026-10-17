import { describe, expect, it, vi } from 'vitest';
import { dataUrl, evidenceMatches, evidenceParts, parseCatalog, parseComparison, safeDataPath, sourceUrl } from '../data';
import { htmlReport } from '../reports';
import { catalog, comparison } from './illustrative-fixture';

describe('source evidence', () => {
  it('uses Unicode code points after an astral character, not UTF16 positions', () => {
    expect(evidenceParts('A 🧭 old amount.', { start: 4, end: 7, quote: 'old' })).toEqual(['A 🧭 ', 'old', ' amount.']);
    expect(evidenceMatches('A 🧭 old amount.', { start: 5, end: 8, quote: 'old' })).toBe(false);
  });
  it('rejects mismatched, negative, fractional and out of range evidence', () => {
    for (const evidence of [{ start: -1, end: 2, quote: 'ab' }, { start: 0.5, end: 2, quote: 'ab' }, { start: 0, end: 9, quote: 'abc' }, { start: 0, end: 2, quote: 'xx' }]) expect(evidenceParts('abc', evidence)).toBeNull();
    expect(evidenceParts('abc', { start: 3, end: 3, quote: '' })).toEqual(['abc', '', '']);
  });
});

describe('contract boundaries', () => {
  it('accepts format 1.0 and stops mismatched comparison entries', () => {
    expect(parseCatalog(catalog)).toEqual(catalog);
    expect(parseComparison(comparison, catalog.comparisons[0])).toEqual(comparison);
    expect(() => parseComparison({ ...comparison, id: 'wrong' }, catalog.comparisons[0])).toThrow('does not match its archive entry');
    expect(() => parseCatalog({ ...catalog, schema_version: '2.0' })).toThrow('format 1.0');
    expect(() => parseCatalog({ ...catalog, comparisons: [...catalog.comparisons, ...catalog.comparisons] })).toThrow('duplicate');
  });
  it('only resolves safe relative archive paths', () => {
    expect(safeDataPath('comparisons/a.json')).toBe(true);
    for (const path of ['../private.json', '/absolute.json', 'https://example.com/a.json', 'comparisons/%2e%2e/a.json', 'comparisons/../a.json', 'a.json?x=1', 'a\\b.json']) expect(safeDataPath(path)).toBe(false);
    expect(sourceUrl('javascript:alert(1)')).toBeUndefined();
  });
  it('resolves archive data under a configured hosting base', () => {
    vi.stubEnv('BASE_URL', '/review/');
    expect(dataUrl('comparisons/a.json')).toBe('/review/data/comparisons/a.json');
    expect(() => dataUrl('../private.json')).toThrow('unsupported data path');
    vi.unstubAllEnvs();
  });
});

describe('downloaded report safety', () => {
  it('escapes source and summary content and omits executable source URLs', () => {
    const input = structuredClone(comparison);
    input.changes[0].summary = '<script>alert("x")</script>';
    input.before.text = '<img src=x onerror="alert(1)">';
    input.before.url = 'javascript:alert(1)';
    const html = htmlReport(input);
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('not verify the explanation');
  });
});
