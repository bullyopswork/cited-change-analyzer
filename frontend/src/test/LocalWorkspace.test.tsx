import { act, cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { catalog, comparison } from './illustrative-fixture';

const token = 'illustrative-test-token';
const localReport = () => {
  const report = structuredClone(comparison);
  report.id = 'local-pair';
  report.before = { ...report.before, url: '', source_kind: 'local', filename: 'earlier.txt', format: 'text' };
  report.after = { ...report.after, url: '', source_kind: 'local', filename: 'revision.pdf', format: 'pdf', pages: [{ number: 1, start: 0, end: 15 }] };
  return report;
};
const bootstrap = { version: '0.2.0', limits: { file_bytes: 10485760, pdf_pages: 50, characters: 100000 }, ai: { configured: true, model: 'illustrative-model', cap_usd: '0.25', reason: null } };
let jobResponse: unknown;
let config: unknown;
let compareError = false;
let requestLog: { path: string; options?: RequestInit }[];
beforeEach(() => {
  window.history.replaceState(null, '', '/');
  const meta = document.createElement('meta');
  meta.name = 'cca-local-token'; meta.content = token; document.head.append(meta);
  config = structuredClone(bootstrap);
  jobResponse = { job_id: 'job-1', status: 'succeeded', stage: 'Local comparison complete', report: localReport() };
  compareError = false;
  requestLog = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, options?: RequestInit) => {
    requestLog.push({ path, options });
    const value = path === '/api/bootstrap' ? config : path === '/api/compare' || path.endsWith('/ai') ? { job_id: 'job-1' } : path.startsWith('/api/jobs/') ? jobResponse : path.endsWith('catalog.json') ? catalog : comparison;
    if (compareError && path === '/api/compare') return { ok: false, status: 422, json: async () => ({ error: 'The PDF has no selectable text.' }) };
    return { ok: true, status: 200, json: async () => value };
  }));
});
afterEach(() => { cleanup(); document.querySelector('meta[name="cca-local-token"]')?.remove(); vi.unstubAllGlobals(); });
async function selectFiles(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByText(/Configured budget cap/);
  await user.upload(screen.getByLabelText('Earlier document'), new File(['A 🧭 old amount.'], 'earlier.txt', { type: 'text/plain' }));
  await user.upload(screen.getByLabelText('Revised document'), new File(['illustrative PDF'], 'revision.pdf', { type: 'application/pdf' }));
}

describe('local document workflow', () => {
  it('does not expose backend processing or key entry in public mode', async () => {
    document.querySelector('meta[name="cca-local-token"]')?.remove();
    render(<App />);
    expect(await screen.findByText('Illustrative wording change.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Install local app ↗' })).toHaveAttribute('href', 'https://github.com/bullyopswork/cited-change-analyzer/releases/tag/v0.2.0');
    expect(screen.queryByLabelText('Earlier document')).not.toBeInTheDocument();
    expect(requestLog.some(({ path }) => path.startsWith('/api/'))).toBe(false);
    expect(document.querySelector('input[type="password"]')).toBeNull();
  });
  it('sends exact file bytes with the injected token and reuses source evidence navigation', async () => {
    const user = userEvent.setup(); render(<App />); await selectFiles(user);
    expect(screen.getByRole('button', { name: 'Run optional AI analysis' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    expect(await screen.findByRole('heading', { name: 'Your document comparison' })).toBeInTheDocument();
    const posted = requestLog.find(({ path }) => path === '/api/compare')!;
    expect(JSON.parse(posted.options!.body as string)).toEqual({ before: { filename: 'earlier.txt', content_base64: 'QSDwn6etIG9sZCBhbW91bnQu' }, after: { filename: 'revision.pdf', content_base64: btoa('illustrative PDF') } });
    for (const call of requestLog.filter(({ path }) => path.startsWith('/api/'))) expect(call.options?.headers).toMatchObject({ 'X-CCA-Token': token });
    expect(screen.getByRole('heading', { name: 'earlier.txt' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'revision.pdf' })).toBeInTheDocument();
    expect(screen.getByText('Selected passage · Page 1')).toBeInTheDocument();
    expect([...document.querySelectorAll('mark')].map((mark) => mark.textContent)).toEqual(['old', 'new']);
    await user.click(screen.getByRole('button', { name: /Illustrative review item/ }));
    expect([...document.querySelectorAll('mark')].map((mark) => mark.textContent)).toEqual(['amount', 'amount']);
    expect(screen.getByRole('button', { name: 'JSON ↓' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'HTML ↓' })).toBeEnabled();
    expect(requestLog.some(({ path }) => path.endsWith('/ai'))).toBe(false);
  });
  it('requires informed AI consent and preserves local evidence when AI fails', async () => {
    const user = userEvent.setup(); render(<App />); await selectFiles(user);
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    await screen.findByRole('heading', { name: 'Your document comparison' });
    expect(screen.getByText(/sent directly to OpenAI using your configured own key/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run optional AI analysis' })).toBeDisabled();
    jobResponse = { job_id: 'job-1', status: 'error', stage: 'AI failed', error: 'API budget exceeded.', local_report: localReport() };
    await user.click(screen.getByRole('checkbox', { name: /I consent/ }));
    await user.click(screen.getByRole('button', { name: 'Run optional AI analysis' }));
    expect(await screen.findByText('API budget exceeded.')).toBeInTheDocument();
    expect(screen.getByText('Your existing local report remains available below.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Your document comparison' })).toBeInTheDocument();
    expect(JSON.parse(requestLog.find(({ path }) => path.endsWith('/ai'))!.options!.body as string)).toEqual({ consent: true });
    expect(screen.getByRole('checkbox', { name: /I consent/ })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'JSON ↓' })).toBeEnabled();
  });
  it('shows configured-false setup status without allowing an AI request', async () => {
    config = { ...bootstrap, ai: { configured: false, model: null, cap_usd: null, reason: 'No local OpenAI key configured.' } };
    render(<App />);
    expect(await screen.findByText(/No local OpenAI key configured/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run optional AI analysis' })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /I consent/ })).not.toBeInTheDocument();
    expect(requestLog.some(({ path }) => path.endsWith('/ai'))).toBe(false);
  });
  it('shows extraction errors and supports a clean retry with selected files', async () => {
    compareError = true;
    const user = userEvent.setup(); render(<App />); await selectFiles(user);
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    expect(await screen.findByText('The PDF has no selectable text.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Compare locally' })).toBeEnabled();
    compareError = false;
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    expect(await screen.findByRole('heading', { name: 'Your document comparison' })).toBeInTheDocument();
  });
  it('rejects oversized inputs before sending file bytes', async () => {
    const user = userEvent.setup(); render(<App />); await selectFiles(user);
    const oversized = new File(['oversize'], 'too-large.txt', { type: 'text/plain' });
    Object.defineProperty(oversized, 'size', { value: 10485761 });
    await user.upload(screen.getByLabelText('Earlier document'), oversized);
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    expect(await screen.findByText(/exceeds the 10 MiB/)).toBeInTheDocument();
    expect(requestLog.some(({ path }) => path === '/api/compare')).toBe(false);
  });
  it('keeps the form locked while a job is pending and resumes when it completes', async () => {
    const user = userEvent.setup(); render(<App />); await selectFiles(user);
    let complete!: (value: unknown) => void;
    jobResponse = new Promise((resolve) => { complete = resolve; });
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    expect(await screen.findByRole('button', { name: 'Working…' })).toBeDisabled();
    expect(screen.getByLabelText('Earlier document')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Run optional AI analysis' })).toBeDisabled();
    await act(async () => { complete({ job_id: 'job-1', status: 'succeeded', stage: 'Complete', report: localReport() }); });
    expect(await screen.findByRole('heading', { name: 'Your document comparison' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Compare locally' })).toBeEnabled();
  });
  it('recovers a lost polling response without resubmitting private file bytes', async () => {
    const user = userEvent.setup(); render(<App />); await selectFiles(user);
    jobResponse = { job_id: 'job-1', status: 'unrecognized', stage: 'Unavailable' };
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    await user.click(await screen.findByRole('button', { name: 'Retry job status' }));
    expect(requestLog.filter(({ path }) => path === '/api/compare')).toHaveLength(1);
    jobResponse = { job_id: 'job-1', status: 'succeeded', stage: 'Complete', report: localReport() };
    await user.click(await screen.findByRole('button', { name: 'Retry job status' }));
    expect(await screen.findByRole('heading', { name: 'Your document comparison' })).toBeInTheDocument();
    expect(requestLog.filter(({ path }) => path === '/api/compare')).toHaveLength(1);
  });
  it('keeps completed local work accessible after exploring archived examples', async () => {
    const user = userEvent.setup(); render(<App />); await selectFiles(user);
    await user.click(screen.getByRole('button', { name: 'Compare locally' }));
    await screen.findByRole('heading', { name: 'Your document comparison' });
    await user.click(screen.getByRole('button', { name: 'Explore examples' }));
    expect(await screen.findByText('Precomputed archive')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Your documents' }));
    expect(screen.getByRole('heading', { name: 'Your document comparison' })).toBeVisible();
  });
});
