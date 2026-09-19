import sys, statistics
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

db=get_supabase()
features=["momentum_5d","momentum_20d","volatility_20d","volume_change_5d"]
companies=db.table("companies").select("id,ticker").execute().data or []

def pearson(xs,ys):
    if len(xs)<3:return None
    mx,my=statistics.mean(xs),statistics.mean(ys)
    num=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    den=(sum((x-mx)**2 for x in xs)*sum((y-my)**2 for y in ys))**0.5
    return num/den if den else None

for c in companies:
    rows=(db.table("price_features").select("*").eq("company_id",c["id"])
          .not_.is_("forward_return_5d","null").order("feature_date").execute().data or [])
    up=sum(bool(r["forward_up_5d"]) for r in rows)/len(rows) if rows else 0
    avg=statistics.mean(float(r["forward_return_5d"]) for r in rows) if rows else 0
    print(f"\n{c['ticker']} n={len(rows)} baseline_up={up:.1%} avg_5d={avg:.2%}")
    for name in features:
        pairs=[(float(r[name]),float(r["forward_return_5d"])) for r in rows if r.get(name) is not None]
        corr=pearson([x for x,_ in pairs],[y for _,y in pairs])
        if corr is not None: print(f"  {name}: corr={corr:+.3f} n={len(pairs)}")
