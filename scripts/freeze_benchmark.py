"""Freeze references, split and inputs before model inference."""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES=['data/benchmark/real-inputs-v2.json','data/benchmark/controlled-inputs.json','data/benchmark/gold-real.json','data/benchmark/gold-controlled.json','prompts/cca-grounded-v1.txt']

def main():
    cases=[];gold=[]
    for f in FILES[:2]:cases.extend(json.loads((ROOT/f).read_text())['cases'])
    for f in FILES[2:4]:gold.extend(json.loads((ROOT/f).read_text())['cases'])
    by_id={c['id']:c for c in cases}
    assert len(by_id)==len(cases)==60
    assert {c['id'] for c in gold}==set(by_id)
    assert len({c['section'] for c in cases})==60
    expected=0
    for item in gold:
        c=by_id[item['id']]
        for e in item['expected']:
            expected+=1
            assert e['before_quote'] is not None or e['after_quote'] is not None
            for side in ('before','after'):
                quote=e[side+'_quote']
                assert quote is None or (isinstance(quote,str) and quote and quote in c[side]['text']), (item['id'],side,quote)
    hashes={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in FILES}
    path=ROOT/'data/benchmark/freeze.json'
    if path.exists():
        previous=json.loads(path.read_text())
        if previous['hashes']!=hashes:raise SystemExit('Frozen benchmark changed; do not silently re-freeze')
        print('Frozen hashes unchanged');return
    obj={'schema_version':'1.0','frozen_at':datetime.now(timezone.utc).isoformat(),'stage':'before_any_model_predictions','hashes':hashes,'case_count':len(cases),'event_count':expected,'splits':dict(Counter(c['split'] for c in cases)),'real_annotation':'Separate source-only Codex agent reference annotation, parent exact-quote checks; not human expert validation','controlled_annotation':'Explicit author-defined synthetic facts','limitations':['Curated small single-corpus benchmark, not representative regulatory or legal validation','Agent references and model use same model family, so correlated errors remain possible','No independent human expert labels','Input selection revised before inference to reduce amendment-notice-only cases; initial selection retained internally'],'targets':{'factual_precision':0.95,'factual_recall':0.85,'displayed_evidence_validity':1.0,'observed_unsupported_release_assertions':0}}
    path.write_text(json.dumps(obj,indent=2)+'\n')
    inference=ROOT/'data/inference';inference.mkdir(parents=True,exist_ok=True)
    for split in ('development','held_out'):
        clean=[{k:c[k] for k in ('id','section','title','corpus','before','after','kind')} for c in cases if c['split']==split]
        (inference/('inputs-'+split+'.json')).write_text(json.dumps({'schema_version':'1.0','cases':clean},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'frozen_cases':len(cases),'events':expected,'splits':obj['splits'],'hashes':hashes},indent=2))

if __name__=='__main__':main()
