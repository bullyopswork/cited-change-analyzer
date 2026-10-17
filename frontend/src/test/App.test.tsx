import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { catalog, comparison } from './illustrative-fixture';

let evaluation: unknown;
let comparisonData: unknown;
let failCatalog = false;
beforeEach(() => {
  evaluation = undefined;
  comparisonData = structuredClone(comparison);
  failCatalog = false;
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    const value = input.endsWith('catalog.json') ? (failCatalog ? undefined : catalog) : input.endsWith('evaluation.json') ? evaluation : comparisonData;
    return { ok: value !== undefined, status: value === undefined ? 404 : 200, json: async () => value };
  }));
});

describe('archive review', () => {
  it('loads only curated pairs and highlights the selected Unicode evidence', async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText('Illustrative wording change.')).toBeInTheDocument();
    expect(screen.getByText('Precomputed archive')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Available date pair')).getAllByRole('option')).toHaveLength(1);
    expect([...document.querySelectorAll('mark')].map((mark) => mark.textContent)).toEqual(['old', 'new']);
    const second = screen.getByRole('button', { name: /Illustrative review item/ });
    await user.click(second);
    expect(second).toHaveAttribute('aria-pressed', 'true');
    expect([...document.querySelectorAll('mark')].map((mark) => mark.textContent)).toEqual(['amount', 'amount']);
    expect(new URLSearchParams(window.location.search).get('change')).toBe('review-2');
    expect(new URLSearchParams(window.location.search).get('comparison')).toBe(comparison.id);
    await user.type(screen.getByLabelText('Search changes'), 'no matching text');
    expect(screen.getByText('No matching changes')).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Clear filters' })[0]);
    expect(screen.getByRole('button', { name: /Illustrative review item/ })).toBeInTheDocument();
    await user.click(screen.getByLabelText('Only needs review'));
    expect(screen.queryByRole('button', { name: /Illustrative wording change/ })).not.toBeInTheDocument();
    expect(screen.getByText('Showing 1 of 2 changes')).toBeInTheDocument();
  });
  it('restores a permalink selection and shows category counts', async () => {
    window.history.replaceState(null, '', '/?comparison=illustrative-pair&change=review-2');
    render(<App />);
    expect(await screen.findByRole('button', { name: /Illustrative review item/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByLabelText('Category')).toHaveTextContent('Requirement (1)');
  });
  it('shows citation mismatch without applying an inaccurate highlight', async () => {
    const invalid = structuredClone(comparison);
    invalid.changes[0].before_evidence!.quote = 'not the source';
    comparisonData = invalid;
    render(<App />);
    expect(await screen.findByText(/recorded quote or offsets do not match/)).toHaveAttribute('role', 'alert');
    expect([...document.querySelectorAll('mark')].map((mark) => mark.textContent)).toEqual(['new']);
    expect(screen.getByText('A 🧭 old amount.')).toBeInTheDocument();
  });
  it('recovers from an unavailable catalog with a bounded user retry', async () => {
    failCatalog = true;
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Archive unavailable' })).toBeInTheDocument();
    failCatalog = false;
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Illustrative wording change.')).toBeInTheDocument();
  });
});

describe('evaluation truthfulness', () => {
  it('shows unavailability rather than demonstration benchmark results', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Evaluation' }));
    expect(await screen.findByRole('heading', { name: 'Evaluation unavailable' })).toBeInTheDocument();
    expect(screen.getByText(/No benchmark results are shown/)).toBeInTheDocument();
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument();
  });
  it('renders actual supplied metrics including zero, failures and methodology', async () => {
    evaluation = { status: 'partial', methods: ['deterministic'], metrics: { matched_citations: 0, evaluated_changes: 3 }, failures: ['One unresolved fixture'], methodology: 'Count exact quote matches only.' };
    window.history.replaceState(null, '', '/?view=evaluation');
    render(<App />);
    expect(await screen.findByText('Count exact quote matches only.')).toBeInTheDocument();
    expect(screen.getByText('matched citations')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('One unresolved fixture')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Download evaluation JSON/ })).toHaveAttribute('href', `${import.meta.env.BASE_URL}data/evaluation.json`);
  });
  it('keeps unpriced account cost distinct from recorded zero API spend', async () => {
    evaluation = { status: 'partial', cost: { additional_api_spend_usd: 0, included_account_cost_usd: null }, usage: { batch_tokens: 654, elapsed_seconds: 1.5 } };
    window.history.replaceState(null, '', '/?view=evaluation');
    render(<App />);
    expect(await screen.findByText('Not priced')).toBeInTheDocument();
    expect(screen.getByText('additional api spend usd')).toBeInTheDocument();
    expect(screen.getByText('included account cost usd')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('654')).toBeInTheDocument();
    expect(screen.getByText('1.5')).toBeInTheDocument();
    expect(screen.queryByText('$0')).not.toBeInTheDocument();
  });
});
