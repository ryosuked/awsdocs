import csv,sys,re
# 使い方: q.py <csv> <PriceDescription/usageType に対する正規表現> [除外の正規表現]
f,pat=sys.argv[1],re.compile(sys.argv[2],re.I); ex=re.compile(sys.argv[3],re.I) if len(sys.argv)>3 else None
r=csv.reader(open(f,encoding='utf-8'))
for row in r:
    if row and row[0]=='SKU': h=row; break
ix={k:i for i,k in enumerate(h)}
seen=set()
for row in r:
    if row[ix['TermType']]!='OnDemand': continue
    s=row[ix['PriceDescription']]+' | '+row[ix['usageType']]
    if not pat.search(s) or (ex and ex.search(s)) or s in seen: continue
    seen.add(s)
    print(f"{row[ix['PricePerUnit']]:>14} {row[ix['Unit']]:<12} {row[ix['StartingRange']]:>8} | {s}")
