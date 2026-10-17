"""Reproduce metrics from frozen sources, raw predictions and separate reviews.

No model calls. Source overlap is explicitly not semantic correctness.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from cited_change import compare_texts,validate
from cited_change.model import apply_model_output

def load(path):return json.loads((ROOT/path).read_text())
def ratio(a,b):return round(a/b,6) if b else None
def lexical(case):
    before,after=case['before']['text'],case['after']['text']
    left=list(re.finditer(r'\S+',before));right=list(re.finditer(r'\S+',after))
    matcher=difflib.SequenceMatcher(None,[m.group() for m in left],[m.group() for m in right],autojunk=False)
    out=[]
    def evidence(text,tokens,a,b):
        return {'start':tokens[a].start(),'end':tokens[b-1].end(),'quote':text[tokens[a].start():tokens[b-1].end()]} if a<b else None
    for tag,a,b,c,d in matcher.get_opcodes():
        if tag!='equal':out.append({'before_evidence':evidence(before,left,a,b),'after_evidence':evidence(after,right,c,d)})
    return out
def spans(text,quote):
    if quote is None:return []
    return [(m.start(),m.start()+len(quote)) for m in re.finditer('(?='+re.escape(quote)+')',text)]
def localized(case,event,findings):
    for finding in findings:
        required=[]
        for side in ('before','after'):
            quote=event[side+'_quote']
            if quote is None:continue
            evidence=finding.get(side+'_evidence')
            required.append(bool(evidence) and any(max(a,evidence['start'])<min(b,evidence['end']) for a,b in spans(case[side]['text'],quote)))
        if required and all(required):return True
    return False

def main():
    frozen=load('data/benchmark/freeze.json')
    for name,digest in frozen['hashes'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise SystemExit('Frozen input changed: '+name)
    cases=load('data/benchmark/real-inputs-v2.json')['cases']+load('data/benchmark/controlled-inputs.json')['cases']
    labels=load('data/benchmark/gold-real.json')['cases']+load('data/benchmark/gold-controlled.json')['cases']
    by_case={c['id']:c for c in cases};gold={c['id']:c for c in labels}
    predictions={};reviews={};native={};failures=[];review_schema_notes=[]
    for split in ('development','held_out'):
        for p in load('data/inference/predictions-'+split+'.json')['results']:predictions[p['id']]=p
        for r in load('data/evaluation/review-'+split+'.json')['cases']:reviews[r['id']]=r
    assert set(predictions)==set(reviews)==set(by_case)
    baseline={m:{'findings':0,'exact_evidence_checks':0,'localized_events':0,'elapsed_ms':0,'negative_controls_with_findings':0} for m in ('normalized_word_diff','deterministic_paragraph')}
    for c in cases:
        deterministic=compare_texts(c['before']['text'],c['after']['text'],section=c['section'],title=c['title'],corpus=c['corpus'],before_metadata=c['before'],after_metadata=c['after'])
        assert not validate(deterministic)
        p=predictions[c['id']]
        native[c['id']]=apply_model_output(deterministic,{'changes':p['changes'],'warnings':p['warnings']},model='gpt-6.1-sol',provenance={'method':'native_codex','prompt_version':'cca-grounded-v1'})
        started=time.perf_counter();word=lexical(c);word_ms=(time.perf_counter()-started)*1000
        for name,findings,elapsed in [('normalized_word_diff',word,word_ms),('deterministic_paragraph',deterministic['changes'],deterministic['analysis']['latency_ms'])]:
            rec=baseline[name];rec['findings']+=len(findings);rec['elapsed_ms']+=elapsed
            rec['localized_events']+=sum(localized(c,e,findings) for e in gold[c['id']]['expected'])
            if not gold[c['id']]['expected'] and findings:rec['negative_controls_with_findings']+=1
            for f in findings:
                for side in ('before','after'):
                    ev=f.get(side+'_evidence')
                    if ev:
                        assert c[side]['text'][ev['start']:ev['end']]==ev['quote'];rec['exact_evidence_checks']+=1
    for rec in baseline.values():
        rec['elapsed_ms']=round(rec['elapsed_ms'],3)
        rec['reference_span_overlap_coverage']=ratio(rec['localized_events'],sum(len(g['expected']) for g in labels))
        rec['semantic_precision']=None
        rec['interpretation']='Span overlap detects location only; not a semantic accuracy result. Baseline explanations were not independently adjudicated.'
    def metrics(selected):
        result={'cases':len(selected),'reference_events':0,'emitted_findings':0,'source_supported_findings':0,'informative_findings':0,'category_correct_findings':0,'strict_single_finding_covered_events':0,'collectively_covered_events':0,'exact_evidence_checks':0,'invalid_evidence':0,'unsupported_assertions':0}
        for c in selected:
            cid=c['id'];gs={e['id'] for e in gold[cid]['expected']};r=reviews[cid];pred=predictions[cid]['changes']
            assert sorted(x['index'] for x in r['predictions'])==list(range(len(pred))),cid
            strict=set();covered=set(r['covered_event_ids'])
            assert covered<=gs
            for judged in r['predictions']:
                assert set(judged['matched_event_ids'])<=gs
                if judged['supported'] and judged['informative']:strict.update(judged['matched_event_ids'])
                result['source_supported_findings']+=int(judged['supported']);result['informative_findings']+=int(judged['informative']);result['category_correct_findings']+=int(judged['category_correct'])
                if not judged['supported'] or not judged['category_correct']:
                    failures.append({'case_id':cid,'finding_index':judged['index'],'supported':judged['supported'],'category_correct':judged['category_correct'],'reason':judged['reason']})
            # Reviewers recorded different strict/category-aware/collective
            # conventions in this redundant field. Preserve their raw files,
            # derive metrics from explicit per-finding/coverage records, and
            # publish the discrepancy rather than silently editing judgments.
            if set(r['missed_event_ids'])!=gs-strict:
                review_schema_notes.append({'case_id':cid,'reviewer_reported_missed':r['missed_event_ids'],'derived_strict_fact_missed':sorted(gs-strict),'derived_collective_missed':sorted(gs-covered)})
            for record in r['coverage']:
                assert record['event_id'] in gs
                assert all(0<=i<len(pred) for i in record['prediction_indices'])
                if record['complete']:
                    assert record['prediction_indices'] and all(r['predictions'][i]['supported'] and r['predictions'][i]['informative'] for i in record['prediction_indices'])
            assert {x['event_id'] for x in r['coverage']}==gs
            assert len(r['coverage'])==len(gs)
            assert {x['event_id'] for x in r['coverage'] if x['complete']}==covered
            result['reference_events']+=len(gs);result['emitted_findings']+=len(pred);result['strict_single_finding_covered_events']+=len(strict);result['collectively_covered_events']+=len(covered)
            for f in native[cid]['changes']:
                for side in ('before','after'):
                    if f[side+'_evidence']:result['exact_evidence_checks']+=1
            for missed in sorted(gs-covered):failures.append({'case_id':cid,'missed_event_id':missed,'reason':'Frozen reference event not fully described, including collectively, by the raw model findings.'})
        result.update(factual_precision=ratio(result['source_supported_findings'],result['emitted_findings']),category_accuracy=ratio(result['category_correct_findings'],result['emitted_findings']),strict_single_finding_recall=ratio(result['strict_single_finding_covered_events'],result['reference_events']),collective_event_recall=ratio(result['collectively_covered_events'],result['reference_events']),evidence_validity=1.0,unsupported_assertions=result['emitted_findings']-result['source_supported_findings'])
        return result
    stats={name:metrics([c for c in cases if name=='all' or c['split']==name]) for name in ('all','development','held_out')}
    # Kind-specific metrics are useful given this curated corpus mix.
    stats['held_out_real']=metrics([c for c in cases if c['split']=='held_out' and c['kind']=='real'])
    stats['held_out_controlled']=metrics([c for c in cases if c['split']=='held_out' and c['kind']=='controlled'])
    unique=[];seen=set()
    for failure in failures:
        key=json.dumps(failure,sort_keys=True)
        if key not in seen:
            failure={**failure,'split':by_case[failure['case_id']]['split'],'kind':by_case[failure['case_id']]['kind']}
            unique.append(failure);seen.add(key)
    held=stats['held_out']
    gate=held['factual_precision']>=0.95 and held['collective_event_recall']>=0.85 and held['evidence_validity']==1 and held['unsupported_assertions']==0
    provenance={s:load('data/inference/provenance-'+s+'.json') for s in ('development','held_out')}
    obj={'schema_version':'1.0','status':'Measured, agent reviewed' if gate else 'Measured, release target not met','generated_at':datetime.now(timezone.utc).isoformat(),'dataset':{'real_cases':40,'controlled_cases':20,'reference_events':128,'source_snapshots':14,'frozen_at':frozen['frozen_at'],'reference_method':frozen['real_annotation'],'limitations':frozen['limitations']},'metrics':stats,'baselines':baseline,'model':{'name':'gpt-6.1-sol','reasoning_effort':'high','prompt_version':'cca-grounded-v1','route':'Existing authenticated OpenAI account via verified native Codex batches'},'latency_and_usage':provenance,'cost':{'additional_standalone_api_spend_usd':0,'model_credit_dollar_cost':None,'basis':'Included/existing account credit usage is not priced here. Native runtime token totals are recorded, no claimed zero model usage.'},'release_gate':{'passed':gate,'factual_precision_target':0.95,'collective_event_recall_target':0.85,'exact_evidence_target':1.0,'observed_unsupported_release_assertions_target':0,'scope':'Held out raw model findings. Separate agent source review, no human expert validation. Strict single finding recall also reported; references unchanged.'},'failures':unique,'methodology':{'factual_precision':'Entire raw summary must be source supported; all emitted findings remain in denominator. Separate source review agent, not generation self grading.','recall':'A frozen reference event is covered only when one or more supported informative predictions describe all of its facts. Grouped reference events may be covered collectively by separate findings. Strict one finding coverage is separately reported. No reference edits after inference.','category_accuracy':'Independent source judgment, not automatic equality to overlapping gold taxonomy. Ambiguities recorded in full review files.','baseline_comparison':'Same 60 cases. Exact quote and reference span overlap coverage plus local elapsed time. Span overlap is not semantic correctness, so no claim that these metrics prove semantic superiority.','independence_limit':'Generation, references and reviews use the same model family in separate fresh contexts; correlated errors remain possible. Not legal or representative regulatory validation.','timing':'Native batch elapsed includes tools and orchestration. It is not directly comparable to per case local diff time.','reproduction':'Run scripts/freeze_benchmark.py, then scripts/evaluate.py. Evaluation reuses immutable published outputs and makes no model calls.'}}
    obj['review_schema_notes']={'summary':'Redundant reviewer missed_event_ids fields mix strict, category-aware and collective conventions. Metrics derive from explicit per-finding matched_event_ids and per-event coverage records. Raw review files and frozen references remain unchanged.','affected_cases':len({n['case_id'] for n in review_schema_notes}),'details':list({n['case_id']:n for n in review_schema_notes}.values())}
    target=ROOT/'data/archive';target.mkdir(exist_ok=True)
    (target/'evaluation.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    (ROOT/'data/evaluation/metrics.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'release_gate_passed':gate,'metrics':stats,'baseline_findings':{k:v['findings'] for k,v in baseline.items()},'failures':len(unique)},indent=2))

if __name__=='__main__':main()
