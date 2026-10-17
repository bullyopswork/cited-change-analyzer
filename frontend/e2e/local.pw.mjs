import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

// Use CCA_BASE_URL pointing at the parent's running `cited-change serve`.
// All files are synthetic in-memory fixtures. No outside requests or AI runs.
const earlier = 'Policy\nEmployees must submit receipts within 10 days.\n';
const revised = 'Policy\nEmployees must submit receipts within 30 days.\n';
function pdf(text) {
  const content = `BT /F1 12 Tf 72 720 Td (${text.replace(/[\\()]/g, '\\$&')}) Tj ET`;
  const objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`];
  let body = '%PDF-1.4\n'; const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(body)); body += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(body);
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')}trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body);
}
async function upload(page, before, after) {
  await page.getByLabel('Earlier document', { exact: true }).setInputFiles(before);
  await page.getByLabel('Revised document', { exact: true }).setInputFiles(after);
  await page.getByRole('button', { name: 'Compare locally', exact: true }).click();
}
async function reportJson(page) {
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'JSON ↓', exact: true }).click();
  return JSON.parse(await fs.readFile(await (await download).path(), 'utf8'));
}
test.beforeEach(async ({ page }) => {
  await page.goto('/');
  test.skip(await page.locator('meta[name="cca-local-token"]').count() === 0, 'Requires the actual local app server, not the public archive preview.');
  await expect(page.getByRole('button', { name: 'Compare locally', exact: true })).toBeVisible();
});

test('actual local TXT job preserves exact source bytes, evidence navigation and report exports', async ({ page }) => {
  const pageErrors = []; const outside = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('request', request => { if (new URL(request.url()).origin !== new URL(page.url()).origin) outside.push(request.url()); });
  await upload(page, { name: 'earlier.txt', mimeType: 'text/plain', buffer: Buffer.from(earlier) }, { name: 'revised.txt', mimeType: 'text/plain', buffer: Buffer.from(revised) });
  await expect(page.getByRole('heading', { name: 'Your document comparison', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'earlier.txt', exact: true })).toBeVisible();
  const report = await reportJson(page);
  expect(report.before.text).toBe(earlier);
  expect(report.after.text).toBe(revised);
  expect(report.before.source_kind).toBe('local');
  expect(report.before.url).toBe('');
  expect(report.changes.length).toBeGreaterThan(0);
  for (const change of report.changes) for (const side of ['before', 'after']) {
    const evidence = change[`${side}_evidence`];
    if (evidence) expect(Array.from(report[side].text).slice(evidence.start, evidence.end).join('')).toBe(evidence.quote);
  }
  await page.locator('.change-card').last().click();
  await expect(page.locator('.document-text mark')).not.toHaveCount(0);
  await page.screenshot({ path: '../.local/qa/local-desktop.png', fullPage: true });
  await page.getByRole('searchbox').fill('nonexistent phrase 938y');
  await expect(page.getByRole('heading', { name: 'No matching changes', exact: true })).toBeVisible();
  await page.locator('.empty-list').getByRole('button', { name: 'Clear filters', exact: true }).click();
  const htmlDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'HTML ↓', exact: true }).click();
  const html = await fs.readFile(await (await htmlDownload).path(), 'utf8');
  expect(html).toContain('Local document report.');
  expect(html).toContain('earlier.txt');
  expect(html).not.toContain('Precomputed archive report.');
  await page.getByRole('button', { name: 'Explore examples', exact: true }).click();
  await expect(page.getByText('Precomputed archive', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Your documents', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your document comparison', exact: true })).toBeVisible();
  const aiButton = page.getByRole('button', { name: 'Run optional AI analysis', exact: true });
  if (await aiButton.count()) await expect(aiButton).toBeDisabled();
  expect(outside).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('actual PDF extraction exposes local pages and works on mobile without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await upload(page, { name: 'earlier.pdf', mimeType: 'application/pdf', buffer: pdf('Submit receipts within 10 days.') }, { name: 'revised.pdf', mimeType: 'application/pdf', buffer: pdf('Submit receipts within 30 days.') });
  await expect(page.getByRole('heading', { name: 'Your document comparison', exact: true })).toBeVisible();
  const report = await reportJson(page);
  expect(report.before.format).toBe('pdf');
  expect(report.before.pages).toHaveLength(1);
  expect(report.before.text).toContain('Submit receipts within 10 days.');
  expect(report.after.text).toContain('Submit receipts within 30 days.');
  await expect(page.getByText(/Selected passage · Page 1/).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const first = await page.locator('.source-panel.earlier').boundingBox();
  const second = await page.locator('.source-panel.later').boundingBox();
  expect(second.y).toBeGreaterThan(first.y);
  await page.screenshot({ path: '../.local/qa/local-mobile.png', fullPage: true });
});

test('actual malformed PDF failure is visible and a new comparison can recover', async ({ page }) => {
  await upload(page, { name: 'broken.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a PDF') }, { name: 'revised.txt', mimeType: 'text/plain', buffer: Buffer.from(revised) });
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Compare locally', exact: true })).toBeEnabled();
  await page.getByLabel('Earlier document', { exact: true }).setInputFiles({ name: 'earlier.txt', mimeType: 'text/plain', buffer: Buffer.from(earlier) });
  await page.getByRole('button', { name: 'Compare locally', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Your document comparison', exact: true })).toBeVisible();
});
