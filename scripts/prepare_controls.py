"""Author-controlled fixtures, explicitly synthetic and separate from real data."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    cases=[];labels=[]
    def add(before,after,events,notes=''):
        n=len(cases)+1;ident=f'control-{n:02d}'
        url='https://github.com/bullyopswork/cited-change-analyzer/blob/main/data/benchmark/controlled-inputs.json'
        source=lambda text,day:{'date':day,'url':url,'snapshot_sha256':hashlib.sha256(text.encode()).hexdigest(),'text':text}
        cases.append({'id':ident,'section':ident,'title':f'Synthetic control {n}','corpus':'Controlled fixtures, synthetic','before':source(before,'2025-01-01'),'after':source(after,'2025-01-02'),'kind':'controlled','split':'development' if n<=10 else 'held_out'})
        expected=[{'id':f'{ident}-event-{i+1}','category':cat,'description':desc,'before_quote':old,'after_quote':new,'substantive':cat not in ('editorial','moved')} for i,(cat,desc,old,new) in enumerate(events)]
        labels.append({'id':ident,'expected':expected,'notes':[notes] if notes else [],'ambiguous':False})
    add('The reimbursement limit is $100.','The reimbursement limit is $150.', [('amount','Reimbursement limit changes from $100 to $150.','$100','$150')])
    add('The allowed share is 20%.','The allowed share is 25%.',[('amount','Allowed share changes from 20% to 25%.','20%','25%')])
    add('This policy applies on 2025-07-01.','This policy applies on 2025-08-01.',[('date','Application date moves from July 1 to August 1, 2025.','2025-07-01','2025-08-01')])
    add('Submit the form by July 15, 2025.','Submit the form by August 15, 2025.',[('date','Submission date changes from July 15 to August 15, 2025.','July 15, 2025','August 15, 2025')])
    add('Employees may obtain approval.','Employees must obtain approval.',[('requirement','Approval wording changes from may to must.','may obtain approval','must obtain approval')])
    add('Claims include travel costs except parking.','Claims include travel costs including parking.',[('requirement','Parking changes from an exception to an included cost.','except parking','including parking')])
    add('Keep   the receipt.','Keep the receipt.',[], 'Spacing only, no factual change expected.')
    add('Use the\napproved form.','Use the approved form.',[], 'Line wrapping only, no factual change expected.')
    add('Keep the receipt.','Keep the receipt.\n\nSubmit a signed declaration.',[('added','A signed declaration instruction is added.',None,'Submit a signed declaration.')])
    add('Keep the receipt.\n\nSubmit a signed declaration.','Keep the receipt.',[('removed','The signed declaration instruction is removed.','Submit a signed declaration.',None)])
    add('Personal travel is allowed.','Personal travel is not allowed.',[('requirement','Personal travel changes from allowed to not allowed.','Personal travel is allowed.','Personal travel is not allowed.')])
    add('Meals must be claimed.','Meals must not be claimed.',[('requirement','Meals change from must be claimed to must not be claimed.','Meals must be claimed.','Meals must not be claimed.')])
    add('Keep the receipt.\n\nSubmit the form.\n\nAwait approval.','Submit the form.\n\nKeep the receipt.\n\nAwait approval.',[('moved','Receipt and form instructions exchange order without changed wording.','Keep the receipt.\n\nSubmit the form.','Submit the form.\n\nKeep the receipt.')], 'Either moved paragraph is an acceptable localization of this single order-change event.')
    add('Keep the receipt.\n\nKeep the receipt.','Keep the receipt.',[('removed','One repeated receipt instruction is removed.','Keep the receipt.',None)], 'Gold quote intentionally repeated; a predicted unique contextual span may localize it.')
    add('The limit is $100. Use form A.','The limit is $100. Use form B.',[('wording','The form identifier changes from A to B, not the amount.','Use form A.','Use form B.')])
    add('Keep receipts, then apply.','Keep receipts; then apply.',[('editorial','A comma changes to a semicolon.','Keep receipts, then apply.','Keep receipts; then apply.')])
    add('🧾 Le plafond est de 100 €.','🧾 Le plafond est de 150 €.',[('amount','The amount changes from 100 euros to 150 euros.','100 €','150 €')])
    add('Meals: limit $100.\n\nHotels: limit $100.','Meals: limit $150.\n\nHotels: limit $100.',[('amount','The meals limit rises from $100 to $150; the hotel limit is unchanged.','Meals: limit $100.','Meals: limit $150.')])
    add('Limit: $100.\n\nDeadline: 2025-07-01.','Limit: $150.\n\nDeadline: 2025-08-01.',[('amount','The limit changes from $100 to $150.','Limit: $100.','Limit: $150.'),('date','The deadline changes from July 1 to August 1, 2025.','2025-07-01','2025-08-01')])
    add('The allowed limit is $100 on 2025-07-01.','The allowed limit is $100 on 2025-07-01.',[], 'Identical text with numbers and a date is a negative control.')
    dest=ROOT/'data/benchmark';dest.mkdir(parents=True,exist_ok=True)
    for name,obj in [('controlled-inputs.json',{'schema_version':'1.0','synthetic':True,'cases':cases}),('gold-controlled.json',{'schema_version':'1.0','annotation_method':'Explicit author-controlled fixtures, not real regulation','cases':labels})]:
        p=dest/name;p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
        print(name,len(obj['cases']),hashlib.sha256(p.read_bytes()).hexdigest())

if __name__=='__main__':main()
