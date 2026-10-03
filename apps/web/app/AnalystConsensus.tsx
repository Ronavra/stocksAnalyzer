import type {AnalystConsensus as Consensus} from "@/lib/api";
const labels:Record<string,string>={strong_buy:"Strong buy",buy:"Buy",hold:"Hold",sell:"Sell",strong_sell:"Strong sell"};
export default function AnalystConsensus({data}:{data?:Consensus|null}){
 if(!data)return <p className="muted">Analyst recommendations have not been collected.</p>;
 return <div className="weeklyEvidence">
  <b>{data.available?`Analyst consensus ${data.score.toFixed(1)} / 100`:`Analyst consensus: neutral 50 / 100 (${data.status.replaceAll("_"," ")})`}</b>
  {data.analyst_count!=null&&<p>{data.analyst_count} analysts{data.buy_share!=null&&` · ${(data.buy_share*100).toFixed(0)}% buy or strong buy`}. Small groups have reduced influence.</p>}
  {data.counts&&<p>{Object.entries(data.counts).map(([key,value])=>`${labels[key]||key}: ${value}`).join(" · ")}</p>}
  {data.observed_at&&<small>Source: {data.source} · provider month {data.period_date} · collected {data.observed_at}. Collection time does not establish when each analyst updated their recommendation.</small>}
  {data.price_targets?.mean!=null&&<p>Analyst price target: mean ${Number(data.price_targets.mean).toFixed(2)}{data.price_targets.low!=null&&data.price_targets.high!=null&&` · range $${Number(data.price_targets.low).toFixed(2)}–$${Number(data.price_targets.high).toFixed(2)}`}. Targets are supplementary and do not affect the weekly score.</p>}
 </div>;
}
