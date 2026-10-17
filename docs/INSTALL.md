# Install and use Cited Change Analyzer

The installed application compares your own TXT and selectable text PDF documents. Python 3.11 or newer is required. No Node, Docker, API key or source checkout is needed for ordinary use. The release wheel contains the browser interface.

Download `cited_change_analyzer-0.2.0-py3-none-any.whl` from the [v0.2 release](https://github.com/bullyopswork/cited-change-analyzer/releases/tag/v0.2.0). Compare its SHA256 with the release's SHA256SUMS file. This is the completed v0.2 release, including the [recorded live verification of optional AI](LIVE_API_VERIFICATION.md).

## macOS and Linux

Check that `python3 --version` reports 3.11 or newer. On a Mac where `python3` is an older system Python, use your installed modern Python command, such as `python3.12`, instead. Install Python from [python.org](https://www.python.org/downloads/) if needed.

From the directory containing the downloaded wheel:

```sh
python3 -m venv .cca-venv
.cca-venv/bin/python -m pip install ./cited_change_analyzer-0.2.0-py3-none-any.whl
.cca-venv/bin/cited-change serve
```

## Windows, PowerShell

Check that `py -3 --version` reports 3.11 or newer. From the download directory:

```powershell
py -3 -m venv .cca-venv
.\.cca-venv\Scripts\python.exe -m pip install .\cited_change_analyzer-0.2.0-py3-none-any.whl
.\.cca-venv\Scripts\cited-change.exe serve
```

The command opens your browser at `http://127.0.0.1:8765`. Keep the terminal open while using the app. If that port is occupied, use `serve --port 8766`. Use `--no-browser` to open the printed address yourself. Press Ctrl+C to stop. The server does not bind to your network or expose a hosted upload service.

## Compare files

1. Select **Earlier document** and **Revised document**.
2. Choose **Compare locally**.
3. Inspect the exact extracted text. PDFs show page ranges and extraction warnings; tables, images, signatures and visual layout are not compared.
4. Select a finding to highlight its supporting passage. Local findings are lexical differences, not AI interpretations.
5. Download JSON or a standalone HTML report. Reports contain the extracted document text, so share them only when intended.

Limits: 10 MiB per file, 50 PDF pages, 100,000 extracted Unicode code points and 2,000 paragraphs. TXT must be UTF-8. Scanned, empty, encrypted or overly complex PDFs are rejected. Some PDFs contain mixed image and selectable text pages; missing text is explicitly warned, not silently described as analyzed.

Local comparison runs in a separate child with outside network access disabled. Work is bounded by parser complexity limits, a 60 second wall timeout, and a 512 MiB RSS watchdog sampled by the parent. Linux additionally applies an address space limit. This is resource protection for a local application, not a general operating system sandbox.

Documents and results stay in memory. Up to four recent comparisons are retained, with idle completed jobs expiring after 30 minutes. Reloading the browser loses its current selection; stopping the app discards its in-memory documents. The OS may still use swap and memory caches. Exported reports and explicit CLI outputs persist where you save them.

## Command line

After activating the virtual environment or using the full installed command path:

```sh
cited-change compare --before earlier.pdf --after revised.txt --output comparison.json --html comparison.html
cited-change validate comparison.json
```

No invented public URLs or effective dates are needed for local documents. Source dates record UTC import time. The original dated XML mode remains available through `--format xml` and its explicit date, URL and section arguments.

## Optional AI using your own account

Local comparison needs none of this setup. AI is off unless you configure it. A ChatGPT sign-in or subscription is not an API key for this application.

Configure these environment variables in the terminal that launches the app:

1. `OPENAI_API_KEY`: your own provider key.
2. `OPENAI_MODEL`: a currently supported OpenAI Responses model with structured JSON output.
3. `OPENAI_INPUT_USD_PER_MILLION` and `OPENAI_OUTPUT_USD_PER_MILLION`: current positive USD prices for that model.
4. `CCA_API_CAP_USD`: a positive per-analysis application cap, default USD1 and maximum USD10.

Use your operating system's trusted environment or secret manager. Do not paste keys into the public demo, source files or reports. The key is read only by the local Python process, never delivered in the browser bundle or app configuration response. Provider usage is billed to the account owning that key. [OpenAI authentication guidance](https://developers.openai.com/api/reference/overview#authentication).

Restart the local server after configuring its environment. Review the local comparison, then explicitly consent and select **Run optional AI analysis**. The app sends extracted source sections directly to OpenAI, not through this project's servers. No owner funded account or credential is included.

Processing uses at most eight requests and bounded source windows. The local result is retained for uncovered changes, oversized passages or failed chunks; partial coverage is marked in warnings and the analysis record. One change whose cited passage exceeds the 20,000 code point window can remain local rather than be silently truncated. Exact quotation checks do not certify an explanation's meaning.

The cost cap uses conservative token reservations and the prices you supplied, not a guaranteed provider billing limit. Unknown outcomes keep their reservation. Cancellation or a network timeout may still incur provider usage. There are no automatic retries. Each explicitly requested analysis has its own persistent accounting ledger and request/deadline limits. A new comparison and explicit AI request are a new budget, not a continuation of a depleted ledger.

Ledger files contain accounting, not documents or keys. They are stored in `XDG_STATE_HOME/cited-change-analyzer` on macOS/Linux, defaulting to `~/.local/state/cited-change-analyzer`, or `LOCALAPPDATA/cited-change-analyzer` on Windows.

The CLI equivalent requires explicit consent and a persistent ledger:

```sh
cited-change explain comparison.json --consent --budget-ledger analysis-budget.sqlite --output explained.json --html explained.html
```

## Upgrade and uninstall

Stop the server, then install the new release wheel into the same virtual environment using that environment's Python and `-m pip install --upgrade <new-wheel>`.

To uninstall, stop the server and run the environment's Python with `-m pip uninstall cited-change-analyzer`. You may then remove only that dedicated virtual environment if no other tool uses it. Your explicitly saved reports and API accounting files remain; review them separately rather than assuming uninstall deletes user data.

## Verification

The repository contains `scripts/verify_install.py`, which installs a wheel in a temporary environment outside the checkout, compares synthetic TXT/PDF/mixed files through the installed CLI and API, verifies bundled assets and local authorization, and cleans up owned processes. No Node is required for that proof. CI runs it on macOS, Windows and Linux with Python 3.11. See actual [workflow results](https://github.com/bullyopswork/cited-change-analyzer/actions/workflows/ci.yml), not configuration alone, for platform verification.
