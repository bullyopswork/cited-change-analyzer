import { createRequire } from 'node:module';
import { copyFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = require('playwright');
const base = process.env.CCA_BASE_URL;
if (!base || !/^http:\/\/127\.0\.0\.1:\d+\/?$/.test(base)) throw new Error('Set CCA_BASE_URL to the owned local application.');
const staging = path.join(root, '.local/demo-video-v02');
const screenshots = path.join(root, 'docs/screenshots');
const media = path.join(root, 'docs/demo');
for (const dir of [staging, screenshots, media]) mkdirSync(dir, { recursive: true });
const earlier = 'Example expense policy\n\nThe reimbursement limit is $100.\n\nEmployees must submit receipts within 10 days.\n\nThis policy takes effect on January 1, 2026.\n';
const revised = 'Example expense policy\n\nThe reimbursement limit is $150.\n\nEmployees must submit receipts within 30 days.\n\nThis policy takes effect on February 1, 2026.\n';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const browser = await chromium.launch({ headless: true, ...(process.env.CCA_BROWSER_EXECUTABLE ? { executablePath: process.env.CCA_BROWSER_EXECUTABLE } : {}) });
async function compare(page) {
  await page.goto(base);
  if (!await page.locator('meta[name="cca-local-token"]').count()) throw new Error('This must be an installed local application, not the public archive.');
  await page.getByLabel('Earlier document', { exact: true }).setInputFiles({ name: 'earlier-policy.txt', mimeType: 'text/plain', buffer: Buffer.from(earlier) });
  await page.getByLabel('Revised document', { exact: true }).setInputFiles({ name: 'revised-policy.txt', mimeType: 'text/plain', buffer: Buffer.from(revised) });
  await pause(2000);
  await page.getByRole('button', { name: 'Compare locally', exact: true }).click();
  await page.getByRole('heading', { name: 'Your document comparison', exact: true }).waitFor();
}
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, recordVideo: { dir: staging, size: { width: 1440, height: 1000 } } });
  try {
    const page = await context.newPage();
    await compare(page);
    await pause(3000);
    await page.screenshot({ path: path.join(screenshots, 'local-desktop.png'), fullPage: true });
    await page.getByRole('heading', { name: 'Your document comparison', exact: true }).scrollIntoViewIfNeeded();
    await pause(2500);
    await page.locator('.change-card').last().click();
    await pause(2500);
    await page.locator('.source-panel').getByRole('button', { name: /jump to evidence/i }).first().click();
    await pause(2500);
    await page.getByRole('searchbox').fill('reimbursement');
    await pause(2500);
    await page.getByRole('searchbox').fill('');
    const downloading = page.waitForEvent('download');
    await page.getByRole('button', { name: 'HTML ↓', exact: true }).click();
    await (await downloading).saveAs(path.join(staging, 'example-policy-report.html'));
    await pause(2500);
    await page.getByRole('heading', { name: 'AI-assisted explanation', exact: true }).scrollIntoViewIfNeeded();
    await pause(3500);
    await page.getByRole('heading', { name: 'Compare your documents', exact: true }).scrollIntoViewIfNeeded();
    await pause(2500);
    const video = page.video();
    await context.close();
    copyFileSync(await video.path(), path.join(media, 'local-walkthrough.webm'));
  } finally { await context.close(); }
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 1 });
  try {
    const page = await mobile.newPage(); await compare(page);
    await page.screenshot({ path: path.join(screenshots, 'local-mobile.png'), fullPage: true });
  } finally { await mobile.close(); }
  console.log(JSON.stringify({ video: 'docs/demo/local-walkthrough.webm', screenshots: ['docs/screenshots/local-desktop.png', 'docs/screenshots/local-mobile.png'] }));
} finally { await browser.close(); }
