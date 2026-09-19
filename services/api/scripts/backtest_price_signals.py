import sys, statistics
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

db=get_supabase()
features=["momentum_5d","momentum_20d","volatility_20d","volume_change_5d","range_pct","close_vs_sma20","volume_ratio_20d"]
companies=db.table("companies").select("id,ticker").execute().data or []

def pearson(xs,ys):
    if len(xs)<3:return None
    mx,my=statistics.mean(xs),statistics.mean(ys)
    num=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    den=(sum((x-mx)**2 for x in xs)*sum((y-my)**2 for y in ys))**0.5
    return num/den if den else None

def stats(rows):
    n=len(rows)
    if not n:return (0,0,0)
    return n,sum(bool(r["forward_up_5d"]) for r in rows)/n,statistics.mean(float(r["forward_return_5d"]) for r in rows)

def fetch_all_features(company_id):
    rows=[]; page_size=1000; start=0
    while True:
        batch=(db.table("price_features").select("*").eq("company_id",company_id)
               .not_.is_("forward_return_5d","null").order("feature_date")
               .range(start,start+page_size-1).execute().data or [])
        rows.extend(batch)
        if len(batch)<page_size: break
        start+=page_size
    return rows

for c in companies:
    rows=fetch_all_features(c["id"])
    cut=max(1,int(len(rows)*0.8)); train,test=rows[:cut],rows[cut:]
    print(f"\n{c['ticker']} total={len(rows)} train={len(train)} test={len(test)}")
    for label,part in [("TRAIN",train),("TEST",test)]:
        n,up,avg=stats(part); print(f" {label}: baseline_up={up:.1%} avg_5d={avg:.2%}")
        for name in features:
            pairs=[(float(r[name]),float(r["forward_return_5d"])) for r in part if r.get(name) is not None]
            corr=pearson([x for x,_ in pairs],[y for _,y in pairs])
            if corr is not None: print(f"   {name}: corr={corr:+.3f} n={len(pairs)}")
