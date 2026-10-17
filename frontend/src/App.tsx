import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { categories, type CatalogEntry, type Change, type Comparison, type Evidence, type Snapshot, dataUrl, displayValue, evidenceParts, fetchJson, friendlyDate, isRecord, parseCatalog, parseComparison, sourceUrl } from './data';
import { downloadReport } from './reports';
import { LocalWorkspace, localToken } from './LocalWorkspace';

type Resource<T> = { path: string; status: 'loading' | 'ready' | 'error'; value?: T; error?: string };
function useResource<T>(path: string | null, parse: (value: unknown) => T) {
  const [resource, setResource] = useState<Resource<T>>({ path: '', status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    setResource({ path, status: 'loading' });
    fetchJson(path, controller.signal).then(parse).then((value) => {
      if (!controller.signal.aborted) setResource({ path, status: 'ready', value });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setResource({ path, status: 'error', error: error instanceof Error ? error.message : 'The archive could not be loaded.' });
    });
    return () => controller.abort();
  }, [path, parse, attempt]);
  return { ...(resource.path === path ? resource : { path: path ?? '', status: 'loading' as const }), retry: () => setAttempt((value) => value + 1) };
}

interface LocationState { id: string; change: string; view: 'compare' | 'evaluation' | 'local' }
function readLocation(): LocationState {
  const query = new URLSearchParams(window.location.search);
  return { id: query.get('comparison') ?? '', change: query.get('change') ?? '', view: query.get('view') === 'evaluation' ? 'evaluation' : query.get('view') === 'local' && localToken() ? 'local' : query.get('view') === 'compare' || query.has('comparison') || !localToken() ? 'compare' : 'local' };
}
function useLocation() {
  const [location, setLocation] = useState(readLocation);
  useEffect(() => { const update = () => setLocation(readLocation()); window.addEventListener('popstate', update); return () => window.removeEventListener('popstate', update); }, []);
  const navigate = (next: LocationState) => {
    const url = new URL(window.location.href);
    (['comparison', 'change', 'view'] as const).forEach((key) => {
      const value = key === 'comparison' ? next.id : next[key];
      if (value && !(key === 'view' && value === 'compare' && !localToken())) url.searchParams.set(key, value); else url.searchParams.delete(key);
    });
    window.history.replaceState(null, '', url);
    setLocation(next);
  };
  return [location, navigate] as const;
}

function Notice({ title, children, error = false, retry }: { title: string; children?: React.ReactNode; error?: boolean; retry?: () => void }) {
  return <div className={`notice ${error ? 'notice-error' : ''}`} role={error ? 'alert' : 'status'}><h2>{title}</h2>{children && <p>{children}</p>}{retry && <button className="button" onClick={retry}>Try again</button>}</div>;
}

function methodLabel(value: unknown) {
  return value === 'native_codex' || value === 'openai_responses' ? 'AI assisted analysis' : value === 'deterministic' ? 'Text diff' : displayValue(value);
}
function cleanTitle(value: string) { return value.replace(/^§+\s*301-10\.\d+\s*/, ''); }

function SourcePanel({ side, snapshot, change }: { side: 'earlier' | 'later'; snapshot: Snapshot; change?: Change }) {
  const markRef = useRef<HTMLElement>(null);
  const markId = useId();
  const evidence = change?.[side === 'earlier' ? 'before_evidence' : 'after_evidence'];
  const parts = evidence ? evidenceParts(snapshot.text, evidence) : null;
  const local = snapshot.source_kind === 'local';
  const url = local ? undefined : sourceUrl(snapshot.url);
  const pages = evidence && parts ? snapshot.pages?.filter((page) => evidence.start < page.end && evidence.end > page.start) : undefined;
  const jump = () => { markRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' }); markRef.current?.focus({ preventScroll: true }); };
  return <section className={`source-panel ${side}`} aria-labelledby={`${markId}-title`}>
    <header className="panel-header">
      <div><span className="eyebrow">{side === 'earlier' ? '02 / Earlier text' : '03 / Later text'}</span><h2 id={`${markId}-title`}>{local ? snapshot.filename || 'Local document' : friendlyDate(snapshot.date)}</h2></div>
      {url ? <a className="source-link" href={url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${side} source dated ${snapshot.date} in a new tab`}>Source ↗</a> : <span className="muted small">{local ? `${snapshot.format?.toUpperCase() || 'Local'} file` : 'Link unavailable'}</span>}
    </header>
    <div className="evidence-bar">
      {parts && parts[1] ? <><span><i className="evidence-dot" />Selected passage{pages?.length ? ` · Page${pages.length > 1 ? 's' : ''} ${pages.map((page) => page.number).join(', ')}` : ''}</span><button className="text-button" onClick={jump}>Jump to evidence ↓</button></> : <span>{evidence && !parts ? 'Evidence could not be matched' : evidence ? 'Evidence marks an insertion point' : change ? 'No cited passage on this side' : 'Select a change to see its evidence'}</span>}
    </div>
    {evidence && !parts && <p className="inline-warning" role="alert">The recorded quote or offsets do not match this snapshot. Highlighting is unavailable; review the source.</p>}
    <div className="document-scroll" tabIndex={0} role="region" aria-label={`${side} source text`}>
      {snapshot.text ? <div className="document-text">{parts ? <>{parts[0]}<mark id={markId} ref={markRef} tabIndex={-1}>{parts[1]}</mark>{parts[2]}</> : snapshot.text}</div> : <div className="absent"><h3>Section absent</h3><p>This dated snapshot contains no section text.</p></div>}
    </div>
    <footer className="source-footer"><details><summary>Snapshot details</summary><p>{local ? 'Imported' : 'Date'}: {snapshot.date}</p>{local && <><p>Filename: {snapshot.filename}</p>{snapshot.pages && <p>Pages: {snapshot.pages.length}</p>}</>}{snapshot.extraction_warnings?.map((warning, index) => <p key={index}>{warning}</p>)}<p>SHA256: <code>{snapshot.snapshot_sha256 || 'Not provided'}</code></p>{url && <a href={url} target="_blank" rel="noopener noreferrer">{url}</a>}</details></footer>
  </section>;
}

function EvidenceQuote({ label, evidence }: { label: string; evidence: Evidence | null }) {
  return <div className="quote"><span>{label}</span>{evidence ? <q>{evidence.quote || 'Insertion point'}</q> : <p>No passage on this side.</p>}</div>;
}

function ComparisonView({ entry, selectedId, onSelect }: { entry: CatalogEntry; selectedId: string; onSelect: (id: string) => void }) {
  const parser = useCallback((value: unknown) => parseComparison(value, entry), [entry]);
  const resource = useResource(entry.path, parser);
  if (resource.status === 'loading') return <Notice title="Loading archived comparison…">Retrieving the two snapshots and recorded changes.</Notice>;
  if (resource.status === 'error' || !resource.value) return <Notice title="Comparison unavailable" error retry={resource.retry}>{resource.error}</Notice>;
  return <ReportView comparison={resource.value} selectedId={selectedId} onSelect={onSelect} />;
}

export function ReportView({ comparison, selectedId, onSelect }: { comparison: Comparison; selectedId: string; onSelect: (id: string) => void }) {
  const [category, setCategory] = useState('all');
  const [query, setQuery] = useState('');
  const [reviewOnly, setReviewOnly] = useState(false);
  const [downloadError, setDownloadError] = useState('');
  const changes = comparison?.changes ?? [];
  const selected = changes.find((change) => change.id === selectedId) ?? changes[0];
  const filtered = changes.filter((change) => (category === 'all' || change.category === category) && (!reviewOnly || change.needs_review) &&
    [change.summary, change.category, change.before_evidence?.quote, change.after_evidence?.quote].join(' ').toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const clearFilters = () => { setCategory('all'); setQuery(''); setReviewOnly(false); };
  const download = (format: 'json' | 'html') => {
    if (!comparison) return;
    try { downloadReport(comparison, format); setDownloadError(''); } catch { setDownloadError('The report could not be downloaded in this browser.'); }
  };
  return <>
    <div className="comparison-heading">
      <div><span className="eyebrow">{comparison.corpus}</span><h1>{comparison.before.source_kind === 'local' ? 'Your document comparison' : `§ ${comparison.section}`}</h1><p>{cleanTitle(comparison.title)}</p></div>
      <div className="report-actions"><span className="small muted">Save this comparison</span><div><button className="button" onClick={() => download('json')}>JSON ↓</button><button className="button" onClick={() => download('html')}>HTML ↓</button></div></div>
    </div>
    {downloadError && <p className="inline-warning" role="alert">{downloadError}</p>}
    <div className="comparison-meta"><span><b>{changes.length}</b> {changes.length === 1 ? 'change' : 'changes'}</span><span><b>{changes.filter((change) => change.needs_review).length}</b> need review</span><span>{methodLabel(comparison.analysis.method)}</span><span className="evidence-note">Evidence linked to source, not a verified interpretation.</span></div>
    {selectedId && !changes.some((change) => change.id === selectedId) && <p className="inline-warning" role="status">The linked change is not available. Showing the first recorded change.</p>}
    {comparison.warnings.length > 0 && <details className="warnings"><summary>{comparison.warnings.length} recorded {comparison.warnings.length === 1 ? 'warning' : 'warnings'}</summary>{comparison.warnings.map((warning, index) => <p key={index}>{displayValue(warning)}</p>)}</details>}
    <div className="review-grid">
      <section className="changes-panel" aria-labelledby="changes-title">
        <header className="panel-header"><div><span className="eyebrow">01 / Change list</span><h2 id="changes-title">What changed</h2></div><span className="count-pill">{changes.length}</span></header>
        <div className="filters"><label htmlFor="search">Search changes</label><input id="search" type="search" placeholder="Summary or cited text" value={query} onChange={(event) => setQuery(event.target.value)} />
          <label htmlFor="category">Category</label><select id="category" value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">All categories ({changes.length})</option>{categories.map((name) => <option key={name} value={name}>{name[0].toUpperCase() + name.slice(1)} ({changes.filter((change) => change.category === name).length})</option>)}</select>
          <label className="checkbox"><input type="checkbox" checked={reviewOnly} onChange={(event) => setReviewOnly(event.target.checked)} />Only needs review</label>
        </div>
        <div className="result-count" role="status">Showing {filtered.length} of {changes.length} changes</div>
        {selected && !filtered.includes(selected) && <div className="hidden-selection">The selected change is hidden by filters. <button className="text-button" onClick={clearFilters}>Clear filters</button></div>}
        <div className="change-list">
          {filtered.length === 0 ? <div className="empty-list"><h3>{changes.length ? 'No matching changes' : 'No changes recorded'}</h3><p>{changes.length ? 'Try another category or search term.' : 'No textual differences were recorded for this pair.'}</p>{changes.length > 0 && <button className="button" onClick={clearFilters}>Clear filters</button>}</div> : filtered.map((change) => <button key={change.id} className={`change-card ${selected?.id === change.id ? 'is-selected' : ''}`} onClick={() => onSelect(change.id)} aria-pressed={selected?.id === change.id}>
            <span className="card-top"><span className={`category category-${change.category}`}>{change.category}</span><span className="change-number">{String(changes.indexOf(change) + 1).padStart(2, '0')}</span></span>
            <span className="change-summary">{change.summary}</span>{change.needs_review && <span className="review-tag">Needs review</span>}<span className="card-hint">{selected?.id === change.id ? 'Selected · evidence shown' : 'View cited passages →'}</span>
          </button>)}
        </div>
        {selected && <div className="selected-detail"><h3>Selected evidence</h3><EvidenceQuote label="Earlier" evidence={selected.before_evidence} /><EvidenceQuote label="Later" evidence={selected.after_evidence} />{selected.needs_review && <p className="inline-warning">{selected.review_reason || 'This change is flagged for human review.'}</p>}<p className="small muted">Method: {selected.method}. A matched quote confirms the citation span, not the explanation.</p></div>}
      </section>
      <SourcePanel side="earlier" snapshot={comparison.before} change={selected} />
      <SourcePanel side="later" snapshot={comparison.after} change={selected} />
    </div>
    <details className="analysis-record"><summary>Analysis record</summary><p>Dollar costs are shown only when recorded. An unpriced included account run does not mean zero usage.</p><FieldValue value={comparison.analysis} /></details>
  </>;
}

function FieldValue({ value, depth = 0, fieldName = '' }: { value: unknown; depth?: number; fieldName?: string }) {
  if (value === null || value === undefined) return <span className="muted">{/(cost|usd|dollar|price)/i.test(fieldName) ? 'Not priced' : /(tokens|latency)/i.test(fieldName) ? 'Not measured for this case' : 'Not provided'}</span>;
  if (depth > 6) return <pre>{displayValue(value)}</pre>;
  if (Array.isArray(value)) return value.length ? <ol className="evaluation-list">{value.map((item, index) => <li key={index}><FieldValue value={item} depth={depth + 1} /></li>)}</ol> : <span className="muted">None recorded</span>;
  if (isRecord(value)) return Object.keys(value).length ? <dl className="field-list">{Object.entries(value).map(([key, item]) => <div key={key}><dt>{key.replace(/_/g, ' ')}</dt><dd><FieldValue value={((key === 'input_tokens' || key === 'output_tokens') && value.usage_available === false) || (key === 'latency_ms' && value.latency_available === false) ? null : item} depth={depth + 1} fieldName={key} /></dd></div>)}</dl> : <span className="muted">None recorded</span>;
  return <span className={typeof value === 'number' ? 'numeric-value' : undefined}>{String(value)}</span>;
}
function parseEvaluation(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error('The evaluation file is not a JSON object.');
  return value;
}

function EvaluationSummary({ evaluation }: { evaluation: Record<string, unknown> }) {
  const [split, setSplit] = useState('held_out');
  const metrics = isRecord(evaluation.metrics) ? evaluation.metrics : {};
  const current = isRecord(metrics[split]) ? metrics[split] : {};
  const all = isRecord(metrics.all) ? metrics.all : {};
  const dataset = isRecord(evaluation.dataset) ? evaluation.dataset : {};
  const pct = (value: unknown) => typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : 'Not recorded';
  const count = (value: unknown) => typeof value === 'number' ? value.toLocaleString('en-US') : 'Not recorded';
  const baseline = isRecord(evaluation.baselines) ? evaluation.baselines : {};
  const failures = Array.isArray(evaluation.failures) ? evaluation.failures.filter(isRecord).filter(f => split === 'all' || f.split === split) : [];
  const cards = [
    ['Source supported summaries', pct(current.factual_precision), `${count(current.source_supported_findings)} of ${count(current.emitted_findings)} summaries`, 'Separate agent source review'],
    ['Reference events covered', pct(current.collective_event_recall), `${count(current.collectively_covered_events)} of ${count(current.reference_events)} events`, 'Across one or several findings'],
    ['Coverage in one finding', pct(current.strict_single_finding_recall), `${count(current.strict_single_finding_covered_events)} of ${count(current.reference_events)} events`, 'Strict complete event matching'],
    ['Category agreement', pct(current.category_accuracy), `${count(current.category_correct_findings)} of ${count(current.emitted_findings)} categories`, 'Independent source judgment'],
    ['Exact source evidence', pct(current.evidence_validity), `${count(current.exact_evidence_checks)} quote checks`, `${count(current.invalid_evidence)} invalid source spans`],
    ['Comparisons reviewed', count(current.cases), `${count(current.emitted_findings)} emitted findings`, `${count(current.unsupported_assertions)} unsupported summaries observed`],
  ];
  return <section className="evaluation-page evaluation-summary" aria-labelledby="evaluation-heading">
    <span className="eyebrow">Reproducible evaluation</span><h1 id="evaluation-heading">Methods and measured results</h1>
    <p className="evaluation-intro">{count(dataset.real_cases)} real historical comparisons, {count(dataset.controlled_cases)} synthetic controls, and {count(dataset.source_snapshots)} source snapshots. Inputs, references and the generation prompt were frozen before inference.</p>
    <div className="metric-tabs" role="group" aria-label="Evaluation split">{[['held_out','Held out'],['development','Development'],['all','All cases']].map(([value,label]) => <button key={value} aria-pressed={split === value} onClick={() => setSplit(value)}>{label}</button>)}</div>
    <div className="metric-grid">{cards.map(([label,value,tally,note]) => <article className="metric-card" key={label}><h2>{label}</h2><strong>{value}</strong><p>{tally}</p><span>{note}</span></article>)}</div>
    <section className="evaluation-section interpretation"><h2>Why two coverage numbers?</h2><p>Some reference events group several edits. Separate findings can collectively describe the complete event without any single finding describing it all. Both measurements are shown. Grouping and category ambiguity affect these results.</p><p>Source matching checks exact quotes. Factual review was performed by separate Codex runs, not human legal experts. The same model family was used for generation and review, so correlated errors remain possible.</p></section>
    <section className="evaluation-section"><h2>Baseline measurements</h2><p className="muted">All 60 cases. Span overlap is location coverage, not semantic correctness or proof that one method is better.</p><div className="method-table-wrap" tabIndex={0} role="region" aria-label="Baseline comparison"><table className="method-table"><thead><tr><th>Method</th><th>Findings</th><th>Reference span overlap</th><th>Semantic source review</th></tr></thead><tbody>{Object.entries(baseline).map(([name,value]) => isRecord(value) && <tr key={name}><th>{name === 'normalized_word_diff' ? 'Normalized word diff' : 'Paragraph alignment'}</th><td>{count(value.findings)}</td><td>{pct(value.reference_span_overlap_coverage)}</td><td>Not adjudicated</td></tr>)}<tr><th>AI assisted analysis</th><td>{count(all.emitted_findings)}</td><td>Reported separately</td><td>{count(all.source_supported_findings)} / {count(all.emitted_findings)} summaries supported</td></tr></tbody></table></div></section>
    <section className="evaluation-section"><h2>Known misses and category questions</h2>{failures.length ? <><p className="muted">{failures.length} recorded {failures.length === 1 ? 'issue' : 'issues'} in this split. Full records are included in the downloadable evaluation.</p><ol className="evaluation-issues">{failures.slice(0,8).map((f,i) => <li key={i}><strong>{typeof f.case_id === 'string' ? f.case_id.split('__')[0] : 'Recorded case'}</strong><p>{typeof f.reason === 'string' ? f.reason : 'See the full review record.'}</p></li>)}</ol></> : <p>No misses or category questions were recorded in this split.</p>}</section>
    <section className="evaluation-section"><h2>Runtime and cost</h2><p>The demo serves precomputed analyses and makes no model calls. Offline generation used the existing authenticated OpenAI account through native Codex. No additional standalone API charges were incurred.</p><p className="cost-note">Included account credits were consumed. Their dollar value is not available here and is not reported as free inference.</p><details><summary>Batch timing and reported token usage</summary><FieldValue value={evaluation.latency_and_usage} /></details><p className="small muted">Batch timings include file access and orchestration. They are not directly comparable to local diff execution time.</p></section>
    <section className="evaluation-section"><h2>Reproduce and inspect</h2><p>Evaluation reads the published sources, raw model outputs and separate review records. It makes no new model calls.</p><div className="evaluation-links"><a className="button" href={dataUrl('evaluation.json')} download="evaluation.json">Download evaluation JSON ↓</a><a href="https://github.com/bullyopswork/cited-change-analyzer" target="_blank" rel="noopener noreferrer">Source, raw outputs and methodology ↗</a></div><details><summary>Full methodology and measurement record</summary><FieldValue value={evaluation} /></details></section>
  </section>;
}
function EvaluationView() {
  const resource = useResource('evaluation.json', parseEvaluation);
  if (resource.status === 'loading') return <Notice title="Loading evaluation record…" />;
  if (resource.status === 'error' || !resource.value) return <Notice title="Evaluation unavailable" retry={resource.retry}>No evaluation record could be loaded. No benchmark results are shown. {resource.error}</Notice>;
  const evaluation = resource.value;
  if (isRecord(evaluation.metrics) && isRecord(evaluation.metrics.held_out)) return <EvaluationSummary evaluation={evaluation} />;
  const hasMetrics = isRecord(evaluation.metrics) ? Object.keys(evaluation.metrics).length > 0 : Array.isArray(evaluation.metrics) && evaluation.metrics.length > 0;
  return <section className="evaluation-page" aria-labelledby="evaluation-heading"><span className="eyebrow">Evaluation record</span><h1 id="evaluation-heading">Methods and measured results</h1><p className="evaluation-intro">This view displays the supplied evaluation file. Citation matching and the quality of a change explanation are different measurements. Recorded API spend is separate from included account credits; an unpriced dollar value does not mean zero usage.</p>
    <div className="evaluation-banner"><span className="category">{typeof evaluation.status === 'string' ? evaluation.status : 'Status not provided'}</span><p>{hasMetrics ? 'Recorded metrics appear below. See the methodology field for their scope.' : 'Evaluation metrics are unavailable. No benchmark success is implied.'}</p></div>
    {Object.entries(evaluation).map(([key, value]) => <section className="evaluation-section" key={key}><h2>{key.replace(/_/g, ' ')}</h2><FieldValue value={value} fieldName={key} /></section>)}
    {!('methodology' in evaluation) && <section className="evaluation-section"><h2>Methodology</h2><p className="muted">Not supplied in this evaluation record.</p></section>}
    <a className="source-link" href={dataUrl('evaluation.json')} download="evaluation.json">Download evaluation JSON ↓</a>
  </section>;
}

export default function App() {
  const [token] = useState(localToken);
  const catalogResource = useResource('catalog.json', parseCatalog);
  const [location, navigate] = useLocation();
  const catalog = catalogResource.value;
  const entries = catalog?.comparisons ?? [];
  const entry = entries.find((item) => item.id === location.id) ?? entries[0];
  const sections = useMemo(() => [...new Map(entries.map((item) => [item.section, item.title])).entries()], [entries]);
  const pairs = entries.filter((item) => item.section === entry?.section);
  const selectEntry = (id: string) => navigate({ ...location, id, change: '' });
  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to main content</a>
    <header className="app-header"><a className="brand" href={import.meta.env.BASE_URL} aria-label="Cited Change Analyzer home"><span className="brand-mark" aria-hidden="true">[c]</span><span>Cited Change<br /><strong>Analyzer</strong></span></a><span className="brand-promise">What changed, with evidence.</span>
      <nav className="view-nav" aria-label="Main views">{token && <button aria-current={location.view === 'local' ? 'page' : undefined} onClick={() => navigate({ ...location, view: 'local' })}>Your documents</button>}<button aria-current={location.view === 'compare' ? 'page' : undefined} onClick={() => navigate({ ...location, view: 'compare' })}>Explore examples</button><button aria-current={location.view === 'evaluation' ? 'page' : undefined} onClick={() => navigate({ ...location, view: 'evaluation' })}>Evaluation</button></nav>
    </header>
    <main id="main-content" tabIndex={-1}>
      {token && <div hidden={location.view !== 'local'}><LocalWorkspace token={token} /></div>}
      {location.view === 'local' && token ? null : location.view === 'evaluation' ? <EvaluationView /> : <>
        {!token && <aside className="install-banner"><div><strong>Compare your own TXT or PDF files locally</strong><p>This public demo displays archived examples. Install v0.2 to compare your own files on your computer, with no account or API key required. Optional AI explanations use your own configured key.</p></div><a className="button" href="https://github.com/bullyopswork/cited-change-analyzer/releases/tag/v0.2.0" target="_blank" rel="noopener noreferrer">Install local app ↗</a></aside>}
        <div className="archive-bar"><div><span className="archive-badge"><i />Precomputed archive</span><p>41 CFR Part 301-10 · Explore available historical comparisons. No account or API key required.</p></div></div>
        {catalogResource.status === 'loading' ? <Notice title="Loading the comparison archive…" /> : catalogResource.status === 'error' ? <Notice title="Archive unavailable" error retry={catalogResource.retry}>{catalogResource.error}</Notice> : entries.length === 0 ? <Notice title="No archived comparisons yet">The catalog is available, but contains no comparison pairs.</Notice> : entry && <>
          <div className="archive-selectors"><div className="section-select"><label htmlFor="section">Section</label><select id="section" value={entry.section} onChange={(event) => { const next = entries.find((item) => item.section === event.target.value); if (next) selectEntry(next.id); }}>{sections.map(([section, title]) => <option key={section} value={section}>§ {section} · {cleanTitle(title)}</option>)}</select></div>
            <div><label htmlFor="pair">Available date pair</label><select id="pair" value={entry.id} onChange={(event) => selectEntry(event.target.value)}>{pairs.map((pair) => <option key={pair.id} value={pair.id}>{friendlyDate(pair.before_date)} → {friendlyDate(pair.after_date)}{pairs.filter((other) => other.before_date === pair.before_date && other.after_date === pair.after_date).length > 1 ? ` · ${pair.method}` : ''}</option>)}</select></div><span className="archive-size">{entries.length} archived {entries.length === 1 ? 'pair' : 'pairs'}</span>
          </div>
          {location.id && !entries.some((item) => item.id === location.id) && <p className="inline-warning" role="status">The linked comparison is not in this archive. Showing the first available pair.</p>}
          <ComparisonView key={entry.id} entry={entry} selectedId={location.change} onSelect={(change) => navigate({ ...location, id: entry.id, change })} />
        </>}
      </>}
    </main>
    <footer className="app-footer"><span>Cited Change Analyzer</span><p>Textual comparison with cited source passages. Not legal advice. Review the source before relying on a change explanation.</p><span>{token ? 'Local app · your files' : '41 CFR Part 301-10'}</span></footer>
  </div>;
}
