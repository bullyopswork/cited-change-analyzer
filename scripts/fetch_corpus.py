"""Fetch bounded, immutable public eCFR snapshots for the curated archive."""
from __future__ import annotations
import argparse
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://www.ecfr.gov/api/versioner/v1'

def get(url: str, limit: int = 4_000_000) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent':'CitedChangeAnalyzer/0.1 (public archive comparison)', 'Accept-Encoding':'gzip'})
    with urllib.request.urlopen(req, timeout=45) as r:
        raw = r.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Compressed response exceeds limit')
        if r.headers.get('Content-Encoding') == 'gzip':
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
                raw = f.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Decoded response exceeds limit')
    return raw

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--dates', nargs='*')
    args = p.parse_args()
    dest = ROOT / 'data' / 'raw'
    dest.mkdir(parents=True, exist_ok=True)
    meta_url = BASE + '/versions/title-41.json?part=301-10'
    meta = get(meta_url)
    (dest / 'versions.json').write_bytes(meta)
    versioned = json.loads(meta)['content_versions']
    # Historical API coverage starts in 2017. Earlier effective dates in
    # metadata are not automatically retrievable snapshot dates.
    requested = args.dates or sorted({str(v['date']) for v in versioned if str(v['date']) >= '2018-01-01'})
    dates = sorted(set(requested) | {p.stem for p in dest.glob('*.xml')})
    if len(dates) > 30:
        raise ValueError('This fetch is limited to 30 snapshots')
    def fetch(date: str) -> dict:
        dt.date.fromisoformat(date)
        url = BASE + '/full/' + date + '/title-41.xml?part=301-10'
        path = dest / (date + '.xml')
        raw = path.read_bytes() if path.exists() else get(url)
        root = ET.fromstring(raw)
        sections = [e for e in root.iter() if e.attrib.get('TYPE') == 'SECTION']
        if not sections:
            raise ValueError('No sections in snapshot ' + date)
        if not path.exists():
            path.write_bytes(raw)
        return {'date':date,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'sections':len(sections),'path':'raw/'+path.name}
    records = []
    errors = []
    # Serialize network requests; honor throttling rather than multiplying it.
    for date in dates:
        try:
            item = fetch(date)
            records.append(item)
            print(item['date'], item['sections'], item['bytes'], flush=True)
        except urllib.error.HTTPError as exc:
            errors.append({'date':date,'http_status':exc.code,'retry_after':exc.headers.get('Retry-After')})
            if exc.code == 429:
                break
            raise
    manifest = {'corpus':'41 CFR Part 301-10','retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(),'metadata_url':meta_url,'metadata_sha256':hashlib.sha256(meta).hexdigest(),'snapshots':sorted(records,key=lambda r:r['date']),'fetch_errors':errors}
    (ROOT/'data'/'sources.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'snapshots':len(records),'bytes':sum(x['bytes'] for x in records)}),flush=True)

if __name__ == '__main__':
    main()
