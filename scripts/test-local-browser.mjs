// Own one installed/local server and one bounded isolated browser-test run.
import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.CCA_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const temporary = await mkdtemp(path.join(os.tmpdir(), 'cca-browser-proof-'));
const environment = { ...process.env };
for (const key of Object.keys(environment)) if (/^(OPENAI_|CCA_API_|PYTHONPATH$|PYTHONHOME$)/.test(key)) delete environment[key];
const server = spawn(python, ['-I', '-m', 'cited_change', 'serve', '--port', '0', '--no-browser'], { cwd: temporary, env: environment, detached: process.platform !== 'win32', stdio: ['ignore', 'pipe', 'pipe'] });
let timer;
let browser;
try {
  const url = await new Promise((resolve, reject) => {
    timer = setTimeout(() => reject(new Error('Local test server did not become ready.')), 20_000);
    let output = '';
    server.stdout.on('data', chunk => {
      output += chunk.toString();
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+\//);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    });
    server.on('error', reject);
    server.on('exit', code => reject(new Error(`Local test server exited (${code}).`)));
  });
  console.log('Testing the bundled local application in an isolated browser.');
  browser = spawn(process.platform === 'win32' ? 'npx.cmd' : 'npx', ['playwright', 'test'], { cwd: path.join(root, 'frontend'), env: { ...environment, CCA_BASE_URL: url }, stdio: 'inherit' });
  const code = await new Promise((resolve, reject) => {
    const expiry = setTimeout(() => { browser.kill(); reject(new Error('Browser proof exceeded five minutes.')); }, 300_000);
    browser.on('error', error => { clearTimeout(expiry); reject(error); });
    browser.on('exit', code => { clearTimeout(expiry); resolve(code ?? 1); });
  });
  process.exitCode = code;
} finally {
  clearTimeout(timer);
  if (browser && browser.exitCode === null) browser.kill();
  if (server.exitCode === null) {
    if (process.platform === 'win32') server.kill();
    else { try { process.kill(-server.pid, 'SIGTERM'); } catch {} }
    await Promise.race([new Promise(resolve => server.once('exit', resolve)), new Promise(resolve => setTimeout(resolve, 3000))]);
    if (server.exitCode === null) {
      if (process.platform === 'win32') server.kill('SIGKILL');
      else { try { process.kill(-server.pid, 'SIGKILL'); } catch {} }
    }
  }
  await rm(temporary, { recursive: true, force: true });
}
