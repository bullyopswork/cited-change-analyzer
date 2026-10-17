// Development/release only. End users install the already built Python wheel.
import { execFileSync } from 'node:child_process';
import { cpSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
execFileSync('node', [path.join(root, 'scripts/build.mjs')], { cwd: root, stdio: 'inherit' });
const bundle = path.join(root, 'src/cited_change/web');
rmSync(bundle, { recursive: true, force: true });
cpSync(path.join(root, 'dist'), bundle, { recursive: true });
console.log('Python package interface prepared. Build the wheel with python -m build.');
