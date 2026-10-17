import { useEffect, useRef, useState } from 'react';
import { isRecord, parseComparison, type Comparison } from './data';
import { ReportView } from './App';

export function localToken(): string | null {
  return document.querySelector<HTMLMetaElement>('meta[name="cca-local-token"]')?.content || null;
}
interface Bootstrap {
  limits: { file_bytes: number; pdf_pages: number; characters: number };
  ai: { configured: boolean; model: string | null; cap_usd: string | null; reason: string | null };
}
type Job = { job_id: string; status: 'running' | 'succeeded' | 'error'; stage: string; report?: Comparison; local_report?: Comparison; error?: string };
async function request(token: string, path: string, signal: AbortSignal, body?: unknown): Promise<unknown> {
  const response = await fetch(path, { signal, method: body === undefined ? 'GET' : 'POST', headers: { 'X-CCA-Token': token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  let value: unknown;
  try { value = await response.json(); } catch { throw new Error('The local app returned an unreadable response. Restart the local app and retry.'); }
  if (!response.ok) throw new Error(isRecord(value) && typeof value.error === 'string' ? value.error : `The local request failed (${response.status}).`);
  return value;
}
function parseBootstrap(value: unknown): Bootstrap {
  if (!isRecord(value) || !isRecord(value.limits) || !isRecord(value.ai) || typeof value.ai.configured !== 'boolean' || !['file_bytes', 'pdf_pages', 'characters'].every((field) => typeof (value.limits as Record<string, unknown>)[field] === 'number' && ((value.limits as Record<string, number>)[field]) > 0)) throw new Error('The local app configuration is unavailable or incompatible. Restart the local app.');
  return value as unknown as Bootstrap;
}
function jobId(value: unknown): string {
  if (!isRecord(value) || typeof value.job_id !== 'string' || !value.job_id) throw new Error('The local app did not return a job identifier.');
  return value.job_id;
}
function parseJob(value: unknown): Job {
  if (!isRecord(value) || !['running', 'succeeded', 'error'].includes(String(value.status)) || typeof value.stage !== 'string') throw new Error('The local app returned an invalid job status.');
  return { job_id: jobId(value), status: value.status as Job['status'], stage: value.stage, ...(value.report ? { report: parseComparison(value.report) } : {}), ...(value.local_report ? { local_report: parseComparison(value.local_report) } : {}), ...(typeof value.error === 'string' ? { error: value.error } : {}) };
}
function encodeFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => typeof reader.result === 'string' ? resolve(reader.result.slice(reader.result.indexOf(',') + 1)) : reject(new Error('This file could not be read. Select it again.'));
    reader.onerror = () => reject(new Error('This file could not be read. Select it again.'));
    reader.readAsDataURL(file);
  });
}
function pause(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => { window.clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = window.setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, 600);
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
}

export function LocalWorkspace({ token }: { token: string }) {
  const [bootstrap, setBootstrap] = useState<Bootstrap>();
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [bootstrapError, setBootstrapError] = useState('');
  const [before, setBefore] = useState<File>();
  const [after, setAfter] = useState<File>();
  const [report, setReport] = useState<Comparison>();
  const [selected, setSelected] = useState('');
  const [activeJob, setActiveJob] = useState('');
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState('');
  const [error, setError] = useState('');
  const [canPoll, setCanPoll] = useState(false);
  const [consent, setConsent] = useState(false);
  const [aiRequested, setAiRequested] = useState(false);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setBootstrapError('');
    request(token, '/api/bootstrap', controller.signal).then(parseBootstrap).then((value) => { if (!controller.signal.aborted) setBootstrap(value); }).catch((reason: unknown) => { if (!controller.signal.aborted) setBootstrapError(reason instanceof Error ? reason.message : 'Local setup could not be loaded.'); });
    return () => controller.abort();
  }, [token, bootstrapAttempt]);

  async function poll(id: string, signal: AbortSignal) {
    while (!signal.aborted) {
      const job = parseJob(await request(token, `/api/jobs/${encodeURIComponent(id)}`, signal));
      if (signal.aborted) return;
      setStage(job.stage);
      if (job.report || job.local_report) setReport(job.report ?? job.local_report);
      if (job.status !== 'running') {
        if (job.status === 'error') setError(job.error || 'The job failed. Your available local report is preserved below.');
        else if (!job.report && !job.local_report) throw new Error('The completed job did not include a report. Retry checking the job.');
        else setError(job.error || '');
        return;
      }
      await pause(signal);
    }
  }
  async function run(kind: 'compare' | 'ai' | 'poll') {
    if (busy) return;
    if (kind === 'compare') {
      if (!before || !after || !bootstrap) return;
      for (const file of [before, after]) {
        if (!/\.(txt|pdf)$/i.test(file.name)) { setError('Choose a TXT or PDF file for both documents.'); return; }
        if (!file.size) { setError(`${file.name} is empty. Choose a document containing selectable text.`); return; }
        if (file.size > bootstrap.limits.file_bytes) { setError(`${file.name} exceeds the ${Math.floor(bootstrap.limits.file_bytes / 1048576)} MiB per-file limit.`); return; }
      }
    }
    if (kind === 'ai' && (aiRequested || !consent || !bootstrap?.ai.configured || !activeJob || !report)) return;
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    setBusy(true); setError(''); setCanPoll(false);
    if (kind === 'compare') { setReport(undefined); setSelected(''); setActiveJob(''); setConsent(false); setAiRequested(false); }
    setStage(kind === 'ai' ? 'Starting optional AI analysis…' : kind === 'poll' ? 'Checking job status…' : 'Reading your selected files…');
    let id = kind === 'compare' ? '' : activeJob;
    try {
      if (kind === 'compare' && before && after) {
        const [beforeData, afterData] = await Promise.all([encodeFile(before), encodeFile(after)]);
        if (controller.signal.aborted) return;
        id = jobId(await request(token, '/api/compare', controller.signal, { before: { filename: before.name, content_base64: beforeData }, after: { filename: after.name, content_base64: afterData } }));
        setActiveJob(id);
      } else if (kind === 'ai') {
        id = jobId(await request(token, `/api/jobs/${encodeURIComponent(activeJob)}/ai`, controller.signal, { consent: true }));
        setAiRequested(true);
        setConsent(false);
      }
      await poll(id, controller.signal);
    } catch (reason: unknown) {
      if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : 'The local request failed.'); setCanPoll(Boolean(id)); }
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  return <section className="local-workspace" aria-labelledby="local-title">
    <div className="local-intro"><span className="eyebrow">On your computer</span><h1 id="local-title">Compare your documents</h1><p>Choose an earlier file and its revision. Text extraction and the initial comparison run locally, with no outside requests. Inspect the exact extracted sources and cited changes below.</p></div>
    <form className="local-form" onSubmit={(event) => { event.preventDefault(); void run('compare'); }} aria-busy={busy}>
      <div className="file-fields"><div><label htmlFor="earlier-file">Earlier document</label><input id="earlier-file" type="file" accept=".txt,.pdf,text/plain,application/pdf" disabled={busy} aria-describedby="file-limits" onChange={(event) => setBefore(event.target.files?.[0])} /></div><div><label htmlFor="revised-file">Revised document</label><input id="revised-file" type="file" accept=".txt,.pdf,text/plain,application/pdf" disabled={busy} aria-describedby="file-limits" onChange={(event) => setAfter(event.target.files?.[0])} /></div></div>
      <p id="file-limits" className="small muted">TXT or selectable-text PDF. {bootstrap ? `Up to ${Math.floor(bootstrap.limits.file_bytes / 1048576)} MiB per file, ${bootstrap.limits.pdf_pages} PDF pages, and ${bootstrap.limits.characters.toLocaleString()} extracted characters. Scanned, encrypted or empty PDFs are not supported.` : 'Loading local file limits…'}</p>
      <button className="button primary-button" type="submit" disabled={busy || !before || !after || !bootstrap}>{busy ? 'Working…' : 'Compare locally'}</button>
    </form>
    {bootstrapError && <div className="inline-warning" role="alert"><p>{bootstrapError}</p><button className="button" onClick={() => setBootstrapAttempt((value) => value + 1)}>Retry local setup</button></div>}
    {!bootstrap && !bootstrapError && <p role="status" className="local-status">Connecting to your local app…</p>}
    {stage && <p className="local-status" role="status">{busy ? 'In progress: ' : 'Job status: '}{stage}</p>}
    {error && <div className="inline-warning" role="alert"><p>{error}</p>{report && <p>Your existing local report remains available below.</p>}{canPoll && <button className="button" disabled={busy} onClick={() => void run('poll')}>Retry job status</button>}</div>}
    {report && <ReportView key={report.id} comparison={report} selectedId={selected} onSelect={setSelected} />}
    {bootstrap && <section className="ai-options" aria-labelledby="ai-title"><div><span className="eyebrow">Optional · separate from local comparison</span><h2 id="ai-title">AI-assisted explanation</h2></div>
      {bootstrap.ai.configured ? <><p>Extracted document sections are sent directly to OpenAI using your configured own key. This may incur API charges. Model: {bootstrap.ai.model || 'Configured model'}. {bootstrap.ai.cap_usd ? `Configured budget cap: $${bootstrap.ai.cap_usd}.` : ''} Review the local report first; an AI failure will not remove it.</p><label className="checkbox"><input type="checkbox" checked={consent} disabled={busy || !report || aiRequested} onChange={(event) => setConsent(event.target.checked)} />I consent to send these extracted document sections to OpenAI.</label><button className="button" disabled={busy || !report || !consent || aiRequested} onClick={() => void run('ai')}>Run optional AI analysis</button>{aiRequested && <p className="small muted">AI was already requested for this comparison. No automatic repeat request will be sent.</p>}</> : <p>{bootstrap.ai.reason || 'AI is not configured.'} To enable it, configure your own OpenAI key in the local app before starting it, then reload this page. No key is entered in this interface. Local comparison remains available.</p>}
    </section>}
  </section>;
}
