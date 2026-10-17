import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

test('real archive renders sources, navigates findings and downloads exact reports', async ({ page }) => {
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  await page.goto('/?view=compare');
  await expect(page.locator('.archive-size')).toHaveText('40 archived pairs');
  await expect(page.locator('.comparison-heading h1')).toBeVisible();
  await expect(page.locator('.source-panel')).toHaveCount(2);
  await expect(page.locator('.document-text mark')).not.toHaveCount(0);
  const sources = await page.locator('.source-panel .panel-header a').evaluateAll(els => els.map(e => e.href));
  expect(sources.every(u => u.startsWith('https://www.ecfr.gov/'))).toBeTruthy();
  const options = await page.locator('#section option').evaluateAll(els => els.map(e => e.value));
  await page.selectOption('#section', options.at(-1));
  await expect(page.locator('.comparison-heading h1')).toHaveText('§ ' + options.at(-1));
  expect(new URL(page.url()).searchParams.get('comparison')).toContain(options.at(-1));
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'JSON ↓', exact: true }).click();
  const download = await downloadPromise;
  const report = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
  expect(report.schema_version).toBe('1.0');
  expect(report.section).toBe(options.at(-1));
  for (const change of report.changes) for (const side of ['before', 'after']) {
    const e = change[side + '_evidence'];
    if (e) expect(Array.from(report[side].text).slice(e.start, e.end).join('')).toBe(e.quote);
  }
  const htmlPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'HTML ↓', exact: true }).click();
  const html = await fs.readFile(await (await htmlPromise).path(), 'utf8');
  expect(html.toLowerCase()).toContain('<!doctype html>');
  expect(errors).toEqual([]);
  await page.screenshot({ path: '../.local/qa/desktop.png', fullPage: true });
});

test('search empty state and filters recover without losing the archive', async ({ page }) => {
  await page.goto('/?view=compare');
  await expect(page.locator('.comparison-heading h1')).toBeVisible();
  const input = page.getByRole('searchbox');
  await input.fill('this phrase deliberately does not occur 99z');
  await expect(page.getByRole('heading', { name: 'No matching changes' })).toBeVisible();
  await page.locator('.empty-list').getByRole('button', { name: /clear filters/i }).click();
  await expect(input).toHaveValue('');
  await expect(page.locator('.change-card').first()).toBeVisible();
});

test('keyboard skip navigation and evaluation work', async ({ page }) => {
  await page.goto('/?view=compare');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#main-content')).toBeFocused();
  await page.getByRole('button', { name: 'Evaluation', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Methods and measured results' })).toBeVisible();
  await expect(page.getByRole('link', { name: /download evaluation json/i })).toBeVisible();
  await page.screenshot({ path: '../.local/qa/evaluation.png', fullPage: true });
});

test('mobile view stacks readable sources with no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?view=compare');
  await expect(page.locator('.comparison-heading h1')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  const earlier = await page.locator('.source-panel.earlier').boundingBox();
  const later = await page.locator('.source-panel.later').boundingBox();
  expect(later.y).toBeGreaterThan(earlier.y);
  expect(Math.abs(later.x - earlier.x)).toBeLessThan(2);
  await page.screenshot({ path: '../.local/qa/mobile.png', fullPage: true });
});

test('missing catalog gives a useful error and can be retried', async ({ page }) => {
  await page.route('**/data/catalog.json', route => route.fulfill({ status: 404, body: 'missing' }));
  await page.goto('/?view=compare');
  await expect(page.getByRole('heading', { name: 'Archive unavailable' })).toBeVisible();
  await page.unroute('**/data/catalog.json');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.locator('.archive-size')).toHaveText('40 archived pairs');
});

test('evaluation shows both coverage definitions and split variation', async ({ page }) => {
  await page.goto('/?view=evaluation');
  await expect(page.getByRole('heading', { name: 'Reference events covered', exact: true }).locator('..')).toContainText('98.4%');
  await expect(page.getByRole('heading', { name: 'Coverage in one finding', exact: true }).locator('..')).toContainText('69.4%');
  await page.getByRole('button', { name: 'Development', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Reference events covered', exact: true }).locator('..')).toContainText('78.8%');
  await expect(page.getByText(/credits were consumed/)).toBeVisible();
});

test('mobile evaluation retains metric cards and contains wide tables', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?view=evaluation');
  await expect(page.locator('.metric-card')).toHaveCount(6);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
});
