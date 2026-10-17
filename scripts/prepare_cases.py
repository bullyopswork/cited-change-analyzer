"""Prepare source-only case inputs before predictions or gold labels exist."""
from __future__ import annotations
import collections
import difflib
import hashlib
import json
import re
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cited_change.extraction import extract_snapshot, section_source

def main():
    snapshots=[]
    for path in sorted((ROOT/'data/raw').glob('*.xml')):
        day=path.stem
        snap=extract_snapshot(path.read_bytes(),date=day,url=f'https://www.ecfr.gov/api/versioner/v1/full/{day}/title-41.xml?part=301-10')
        snapshots.append(snap)
    candidates=[]
    for before,after in zip(snapshots,snapshots[1:]):
        for section in sorted(set(before['sections'])|set(after['sections'])):
            old=section_source(before,section);new=section_source(after,section)
            if not re.fullmatch(r'301-10\.\d+',section):
                continue
            if old['text']==new['text'] or max(len(old['text']),len(new['text']))>6000:
                continue
            blocks=[x for x in difflib.SequenceMatcher(None,old['text'].split(),new['text'].split(),autojunk=False).get_opcodes() if x[0]!='equal']
            # Keep the first benchmark interpretable, not a long-document claim.
            if len(blocks)>12 or max(len(old['text']),len(new['text']))<80:
                continue
            title=after['sections'].get(section,before['sections'].get(section))['title']
            def without_notices(text):
                return '\n\n'.join(p for p in text.split('\n\n') if not p.startswith('Link to an amendment') and not re.match(r'^\[.*(?:FR |FTR)',p))
            notices_only=without_notices(old['text'])==without_notices(new['text'])
            candidates.append({'id':f'{section}__{before["date"]}__{after["date"]}','section':section,'title':title,'corpus':'41 CFR Part 301-10','before':old,'after':new,'word_edit_blocks':len(blocks),'source_notice_only':notices_only,'kind':'real'})
    # Select round-robin by transition, then unique section. Adjacent snapshots
    # represent retrieved dates, not an assertion that every date is an amendment.
    groups=collections.defaultdict(list)
    for c in candidates:
        if not c['source_notice_only']:
            groups[c['after']['date']].append(c)
    for group in groups.values():
        group.sort(key=lambda c:(not(bool(c['before']['text']) and bool(c['after']['text'])),c['word_edit_blocks'],c['section']))
    selected=[];seen=set()
    while len(selected)<36 and any(groups.values()):
        for date in sorted(groups):
            while groups[date]:
                c=groups[date].pop(0)
                if c['section'] not in seen:
                    selected.append(c);seen.add(c['section']);break
            if len(selected)>=36:break
    for c in candidates:
        if len(selected)>=40:break
        if c['source_notice_only'] and c['section'] not in seen:
            selected.append(c);seen.add(c['section'])
    if len(selected)<40:
        raise SystemExit(f'Only {len(selected)} eligible unique sections, do not invent cases')
    # Section grouping is automatic because each selected section is unique.
    selected.sort(key=lambda c:hashlib.sha256(('cca-v1-split:'+c['section']).encode()).hexdigest())
    for i,c in enumerate(selected):c['split']='development' if i<20 else 'held_out'
    dest=ROOT/'data/benchmark';dest.mkdir(parents=True,exist_ok=True)
    payload={'schema_version':'1.0','selection':'Pre inference v2 curation: 36 content edits plus 4 source notice controls; 40 unique individual sections; 80 to 6000 Unicode code points; <=12 word edit regions; round robin by available transition prioritizing short in-place edits. Source notices retained in original text. Curated, not representative. Supersedes initial source notice heavy selection before predictions.','cases':selected}
    path=dest/'real-inputs-v2.json';path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'candidate_pairs':len(candidates),'selected':len(selected),'date_transitions':dict(collections.Counter(c['before']['date']+' to '+c['after']['date'] for c in selected)),'inputs_sha256':hashlib.sha256(path.read_bytes()).hexdigest()},indent=2))

if __name__=='__main__':main()
