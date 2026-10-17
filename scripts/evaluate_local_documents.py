"""Replay public synthetic TXT/PDF fixtures without model or network calls."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'src'))
from cited_change.local_compare import compare_documents
from cited_change.validation import validate
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pdf(text):
    writer=PdfWriter()
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    reference=writer._add_object(font)
    for paragraph in text.split('\n\n'):
        page=writer.add_blank_page(width=612,height=792)
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):reference})})
        stream=DecodedStreamObject()
        escaped=paragraph.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
        stream.set_data(('BT /F1 12 Tf 72 720 Td ('+escaped+') Tj ET').encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream)
    result=io.BytesIO();writer.write(result);return result.getvalue()


def main():
    fixtures=ROOT/'data/benchmark/local-documents-v02.json'
    raw=fixtures.read_bytes();cases=json.loads(raw)['cases'];results=[]
    for case in cases:
        formats=[('txt','txt')] if case.get('text_only') else [('txt','txt'),('pdf','pdf'),('txt','pdf')]
        for before_format,after_format in formats:
            old=case['before'].encode() if before_format=='txt' else pdf(case['before'])
            new=case['after'].encode() if after_format=='txt' else pdf(case['after'])
            start=time.perf_counter()
            report=compare_documents(old,'earlier.'+before_format,new,'revised.'+after_format)
            elapsed=(time.perf_counter()-start)*1000
            exact=not validate(report)
            if case.get('unchanged'):
                matched=not report['changes']
            else:
                matched=any(change['category']==case['category'] and
                            all(not case.get(key) or (change[side+'_evidence'] is not None and case[key] in change[side+'_evidence']['quote'])
                                for key,side in [('old','before'),('new','after')]) for change in report['changes'])
            results.append({'case':case['id'],'formats':before_format+'/'+after_format,'exact_citations':exact,'expected_behavior':matched,'changes':len(report['changes']),'elapsed_ms':round(elapsed,3)})
    result={'scope':'Synthetic local TXT/PDF regression checks. Not semantic, AI, legal, real-world or held-out accuracy.',
            'fixture_sha256':hashlib.sha256(raw).hexdigest(),'checks':len(results),
            'exact_citations':sum(x['exact_citations'] for x in results),
            'expected_behavior':sum(x['expected_behavior'] for x in results),
            'ai_calls':0,'results':results}
    destination=ROOT/'data/evaluation/local-documents-v02.json'
    destination.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='results'}))
    return int(result['exact_citations']!=len(results) or result['expected_behavior']!=len(results))


if __name__=='__main__':raise SystemExit(main())
