"""Build the public archive from frozen real cases and validated model records."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cited_change import compare_texts,validate
from cited_change.provenance import connect,record_comparison

def main():
    p=argparse.ArgumentParser();p.add_argument('--method',choices=['deterministic','native_codex'],default='deterministic');args=p.parse_args()
    cases=json.loads((ROOT/'data/benchmark/real-inputs-v2.json').read_text())['cases']
    predictions={}
    if args.method=='native_codex':
        from cited_change.model import apply_model_output
        for split in ('development','held_out'):
            batch=json.loads((ROOT/f'data/inference/predictions-{split}.json').read_text())
            for c in batch['results']:predictions[c['id']]=c
    target=ROOT/'data/archive';reports=target/'comparisons';reports.mkdir(parents=True,exist_ok=True)
    internal=ROOT/'.local';internal.mkdir(exist_ok=True)
    # Generated-at values are not source identity. The on-disk public report is
    # reused when its inputs and method are unchanged, preserving reproducibility.
    entries=[];all_reports=[];errors=[]
    for c in cases:
        report=compare_texts(c['before']['text'],c['after']['text'],section=c['section'],title=c['title'],corpus=c['corpus'],before_metadata=c['before'],after_metadata=c['after'])
        report['id']=c['id']+'__'+args.method
        report_path=reports/(report['id']+'.json')
        input_identity=hashlib.sha256(json.dumps({'case':c,'prediction':predictions.get(c['id']) if args.method=='native_codex' else None},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if report_path.exists():
            previous=json.loads(report_path.read_text())
            if previous.get('analysis',{}).get('input_identity')==input_identity:
                report=previous
        if report['analysis'].get('input_identity')!=input_identity:
            if args.method=='native_codex':
                raw=predictions.get(c['id'])
                if raw is None:raise SystemExit('Missing actual native model output '+c['id'])
                try:
                    report=apply_model_output(report,{'changes':raw['changes'],'warnings':raw.get('warnings',[])},model='gpt-6.1-sol',provenance={'method':'native_codex','prompt_version':'cca-grounded-v1','cost_usd':None,'billing_basis':'Existing OpenAI account via native Codex. Credit dollar rate unavailable; not zero model usage.'})
                except ValueError as exc:
                    errors.append({'id':c['id'],'error':str(exc)})
                    continue
            report['analysis']['input_identity']=input_identity
            report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        invalid=validate(report)
        if invalid:raise SystemExit(str((c['id'],invalid)))
        all_reports.append(report)
        entries.append({'id':report['id'],'section':c['section'],'title':c['title'],'before_date':c['before']['date'],'after_date':c['after']['date'],'change_count':len(report['changes']),'categories':sorted(set(x['category'] for x in report['changes'])),'path':'comparisons/'+report_path.name,'method':args.method})
    if errors:
        (ROOT/'.local/import-errors.json').write_text(json.dumps(errors,indent=2)+'\n')
        raise SystemExit(f'{len(errors)} rejected model case(s), no public catalog updated; see .local/import-errors.json')
    archive_key=hashlib.sha256(''.join(r['analysis']['input_identity'] for r in all_reports).encode()).hexdigest()[:16]
    db=connect(internal/('provenance-'+args.method+'-'+archive_key+'.sqlite'))
    try:
        for report in all_reports:record_comparison(db,report)
    finally:db.close()
    entries.sort(key=lambda e:(e['after_date'], -int(e['section'].split('.')[-1])),reverse=True)
    catalog={'schema_version':'1.0','title':'Cited Change Analyzer','corpus':'41 CFR Part 301-10','generated_at':datetime.now(timezone.utc).isoformat(),'description':'A curated archive of factual textual changes with dated source evidence. Precomputed analyses, no live model calls.','comparisons':entries}
    (target/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    if not (target/'evaluation.json').exists():
        (target/'evaluation.json').write_text(json.dumps({'status':'Evaluation in progress','metrics':None,'methodology':'Source references and a separate held out set are frozen before inference. No benchmark results are available yet.'},indent=2)+'\n')
    public=ROOT/'frontend/public/data';public.mkdir(parents=True,exist_ok=True)
    for name in ('catalog.json','evaluation.json'):shutil.copy2(target/name,public/name)
    (public/'comparisons').mkdir(exist_ok=True)
    for e in entries:shutil.copy2(target/e['path'],public/e['path'])
    print(json.dumps({'method':args.method,'comparisons':len(entries),'findings':sum(e['change_count'] for e in entries),'all_exact_evidence_valid':True,'sqlite_archive':str(internal/('provenance-'+args.method+'-'+archive_key+'.sqlite'))},indent=2))

if __name__=='__main__':main()
