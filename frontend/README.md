# Cited Change Analyzer viewer

Responsive React and TypeScript viewer for the version 1.0 contract in `../contracts/FORMAT.md`.

## Commands

1. `npm install`
2. `npm run dev` for local development, or `npm run build` for the static production bundle.
3. `npm test` and `npm run typecheck` for verification.

No backend, API key, external fonts, image assets, model requests or live comparisons are used. The development server binds to localhost.

## Data delivery

The viewer requests `data/catalog.json` relative to Vite's base URL. Each catalog comparison path resolves below the same `data/` directory. Evaluation is requested separately at `data/evaluation.json`. Missing evaluation data is presented as unavailable.

For a static build, the parent pipeline should copy the real archive into `frontend/public/data/` before building, or copy it into `frontend/dist/data/` afterward. The viewer does not generate or modify archive data. With a development server, provide real files under `public/data/`. A configured Vite base such as `--base=/review/` is supported. Hosting must preserve that directory structure.

Only existing catalog entries are selectable. Permalinks use `?comparison=ID&change=CHANGE_ID`; evaluation uses `?view=evaluation`. The selected comparison and change update the current URL without adding a history entry on each selection.

Unicode highlights convert the source to code points before slicing. A mismatched citation is not highlighted and displays an explicit warning. A matched quote is not described as a semantically verified explanation. JSON exports preserve the comparison record. HTML exports escape all source text and allow only HTTP or HTTPS source links.

Illustrative fixtures exist only in `src/test/illustrative-fixture.ts` and are not public archive data. Unit and interaction tests cover evidence offsets, contract boundaries, safe exports, selection, filters, missing files, retry, and actual evaluation values. Browser rendering and real archive integration require separate verification by the parent.

Analysis and evaluation records support null dollar costs. Null pricing fields display as “Not priced,” never as zero. API spend and included account usage retain their separate supplied field names. Token counts and elapsed time are displayed only if the evaluation data supplies them.
