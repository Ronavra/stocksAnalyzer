"use client";
import {useMemo,useState} from "react";
import Link from "next/link";
import type {Candidate} from "@/lib/api";
const pct=(v:number|null,d=1)=>v==null?"—":`${(v*100).toFixed(d)}%`;
const num=(v:number|null,d=1)=>v==null?"—":v.toFixed(d);
export default function SetupTable({rows}:{rows:Candidate[]}){
 const [page,setPage]=useState(1); const per=25; const pages=Math.max(1,Math.ceil(rows.length/per));
 const shown=useMemo(()=>rows.slice((page-1)*per,page*per),[rows,page]);
 return <><div className="tableScroll"><table className="setupTable"><thead><tr>
  <th>Ticker</th><th>Company</th><th>Sector</th><th>Price</th><th>Date</th><th>Research rank</th><th>Earnings catalyst</th><th>Opportunity</th><th>Hist. up</th><th>Median 5d</th><th>To 60d high</th><th>60d drawdown</th><th>Samples</th>
 </tr></thead><tbody>{shown.map(x=><tr key={x.ticker}>
  <td><Link className="ticker" href={`/company/${x.ticker}`}>{x.ticker}</Link></td><td>{x.company}</td><td>{x.sector||"—"}</td><td>{x.current_price==null?"—":Number(x.current_price).toFixed(2)}</td><td>{x.price_date||x.as_of_date||"—"}</td><td><b>{num(x.research_rank_score)}</b></td>
  <td>{x.earnings_catalyst?<span className="catalystCell"><b>{x.earnings_catalyst.reported_date}</b><small>EPS {x.earnings_catalyst.surprise_percent==null?"—":`${Number(x.earnings_catalyst.surprise_percent)>=0?"+":""}${Number(x.earnings_catalyst.surprise_percent).toFixed(1)}%`} · Rev {x.earnings_catalyst.revenue_surprise_percent==null?"—":`${Number(x.earnings_catalyst.revenue_surprise_percent)>=0?"+":""}${Number(x.earnings_catalyst.revenue_surprise_percent).toFixed(1)}%`}</small></span>:"—"}</td>
  <td>{num(x.opportunity_score)}</td><td>{pct(x.setup_probability_up)}</td><td>{pct(x.setup_median_return_5d)}</td><td>{pct(x.upside_to_60d_high)}</td><td>{pct(x.setup_drawdown_60d)}</td><td>{x.setup_sample_size??"—"}</td>
 </tr>)}</tbody></table></div>
 <div className="tablePager"><span>Showing {(page-1)*per+1}–{Math.min(page*per,rows.length)} of {rows.length} stocks</span><div><button disabled={page===1} onClick={()=>setPage(p=>p-1)}>←</button><span>Page {page} / {pages}</span><button disabled={page===pages} onClick={()=>setPage(p=>p+1)}>→</button></div></div></>
}
