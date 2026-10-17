import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const catalog = path.join(root, 'frontend/public/data/catalog.json');
if (!existsSync(catalog) || !JSON.parse(readFileSync(catalog, 'utf8')).comparisons?.length) {
  throw new Error('A real archive must exist before building. Run scripts/build_archive.py.');
}
execFileSync('npm', ['--prefix', 'frontend', 'run', 'build'], { cwd: root, stdio: 'inherit' });
const destination = path.join(root, 'dist');
rmSync(destination, { recursive: true, force: true });
cpSync(path.join(root, 'frontend/dist'), destination, { recursive: true });
console.log('Static release prepared in dist/');
