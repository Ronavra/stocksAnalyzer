export type AnalystConsensus = {
 score:number; available:boolean; status:string; analyst_count:number|null; source:string|null;
 observed_at:string|null; period_date:string|null; buy_share?:number;
 counts?:Record<string,number>; price_targets?:{low?:number|null;mean?:number|null;median?:number|null;high?:number|null};
};
export type Candidate = {
 ticker:string; company:string; sector:string|null; signal:string; score:number|null; coverage:number|null; catalyst:string|null;
 fundamentals:number|null; valuation:number|null; earnings:number|null; pe:number|null; price_to_fcf:number|null; as_of_date:string;
 opportunity_score:number|null; setup_probability_up:number|null; setup_median_return_5d:number|null; setup_sample_size:number|null;
 upside_to_60d_high:number|null; setup_drawdown_60d:number|null; opportunity_reason:string|null; current_price:number|null; price_date:string|null; price_source:string|null;
 research_rank_score:number|null; catalyst_adjustment:number|null; earnings_catalyst:{reported_date:string;surprise_percent:number|null;revenue_surprise_percent:number|null;source:string}|null;
 financial_ranking?:{score:number;coverage:number;period_end:string}|null; financial_ranking_status?:string; ranking_weights?:Record<string,number>;
 analyst_consensus?:AnalystConsensus|null;
};
const API_URL=process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function apiFetch(path:string, init:RequestInit={}){
 try{
  return await fetch(`${API_URL}${path}`,init);
 }catch(err){
  console.error(`API fetch failed: ${API_URL}${path}`,err);
  return null;
 }
}
export async function getCandidates():Promise<Candidate[]>{
 const res=await apiFetch("/api/v1/research/candidates",{cache:"no-store"});
 if(!res?.ok) return [];
 return res.json();
}
export async function getCompany(ticker:string){
 const res=await apiFetch(`/api/v1/research/companies/${ticker}`,{next:{revalidate:300}});
 if(!res?.ok) return null;
 return res.json();
}
export type AuditLayer={key:string;label:string;companies:number;total:number;coverage_pct:number;status:string};
export type FinancialGap={ticker:string;status:string;ttm_period?:string|null;latest_report?:{period_end:string}|null;missing_fields?:string[]};
export type DataAudit={universe:number;layers:AuditLayer[];missing_price_tickers:string[];notes:string[];financial_checked_at?:string|null;financial_quality?:{universe_checked:number;current_ttm:number;current_complete:number;field_coverage:Record<string,number>;status_counts:Record<string,number>}|null;financial_gaps?:FinancialGap[]};
export async function getDataAudit():Promise<DataAudit>{
 const res=await apiFetch("/api/v1/research/data-audit",{cache:"no-store"});
 if(!res?.ok) return {universe:503,layers:[] as AuditLayer[],missing_price_tickers:[] as string[],notes:["Backend unavailable"]};
 return res.json();
}

export async function getSignals(){
 const res=await apiFetch("/api/v1/research/signals",{cache:"no-store"}); if(!res?.ok)return []; return res.json();
}
export async function getScorecard(){
 const res=await apiFetch("/api/v1/research/scorecard",{cache:"no-store"}); if(!res?.ok)return {overall:{evaluated:0,win_rate:null,avg_return:null,median_return:null,avg_excess_return:null,beat_spy_rate:null},by_horizon:{}}; return res.json();
}

export async function getSystemHealth(){
 const res=await apiFetch("/api/v1/research/system-health",{cache:"no-store"});
 if(!res?.ok)return {status:"unavailable",last_run:null,latest_price_date:null,latest_feature_date:null,research_sources_run:null,model_validation:null,coverage:{universe:503,fundamentals:0,earnings:0,valuation:0,estimates:0}};
 return res.json();
}
