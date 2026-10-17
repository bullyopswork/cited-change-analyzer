# Public demo deployment

The canonical public demo is https://bullyopswork.github.io/cited-change-analyzer/.

## Current release

GitHub Pages serves the `gh-pages` branch at its root, with HTTPS enabled. The current demo commit is `f95f2ffab9df8b156f8e43d6a077e4e9a56093d3`. It contains 86 verified static application files plus `.nojekyll`.

The website displays 40 archived comparisons and links to the installable local application. It has no upload server, API key or owner funded inference endpoint. Users compare their own documents in the installed application. Optional AI using the installer's key passed its scoped live provider check on October 17, 2026; see [verification and limits](LIVE_API_VERIFICATION.md).

The website remains an example archive. Its installation banner now describes the completed v0.2 tool and clearly separates local comparison without a key from optional AI using the installer's own key. Only that banner changed from the earlier deployment `992868e900da9c272d60e5d93f3ddace3391ce5e`. Comparison data, evaluation and installed release files are unchanged. The original download and source tag retain their recorded identities; historical verification receipts are preserved.

All 86 files were downloaded anonymously from the live site and matched the release hashes. Eight live desktop/mobile browser flows passed, covering source evidence, filtering, keyboard navigation, reports, evaluation, error recovery, installation links and the public demo boundary.

## Updating the demo

1. Build the reviewed static archive using the repository build instructions. Keep relative asset and data paths so the app works below `/cited-change-analyzer/`.
2. Verify the production artifact and the browser flows at that URL prefix. Publish only static application files and `.nojekyll`, not a source checkout, local records, credentials or user documents.
3. Commit the reviewed artifact to `gh-pages` with normal Git safeguards. A push triggers the GitHub Pages deployment. Preserve `main` as the source branch and do not force overwrite unrelated work.
4. Read the Pages build result and verify the real public URL anonymously. A successful local preview alone is not a deployment proof.

The prior ChatGPT Sites deployment is retained privately as an owner backup, not as the public demo. The retained `.openai/hosting.json` identifies that backup. Do not treat it as the current public deployment target or change its audience without explicit owner authorization.
