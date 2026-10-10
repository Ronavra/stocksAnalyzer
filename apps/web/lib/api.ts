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
 upcoming_earnings?:{reported_date:string;within_execution_horizons?:number[]}|null;earnings_risk_excluded?:boolean;
};
const API_URL=process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
 constructor(public section:string, public status:number|null=null){
  super(status===404?"Company not found":status?`Data service returned ${status}. Retry shortly.`:"Cannot reach the data service. Check that the API is running and retry.");
 }
}
async function apiFetch(path:string, init:RequestInit={}){
 let res:Response;
 try{res=await fetch(`${API_URL}${path}`,{...init,signal:AbortSignal.timeout(30000)});}
 catch{throw new ApiError(path);}
 if(!res.ok && !(res.status===404 && path.startsWith("/api/v1/research/companies/"))) throw new ApiError(path,res.status);
 return res;
}
export async function safeLoad<T>(load:()=>Promise<T>,fallback:T):Promise<{data:T;error:string|null}>{
 try{return {data:await load(),error:null};}
 catch(err){return {data:fallback,error:err instanceof ApiError?err.message:"Data could not be loaded. Retry shortly."};}
}
export type Cohort={signal_date:string;model_version:string;horizons:number[];expected_picks:number;status:string;published_at:string};
export async function getCohorts():Promise<Cohort[]>{return (await apiFetch("/api/v1/research/cohorts",{cache:"no-store"})).json();}
export async function getCandidates():Promise<Candidate[]>{
 const res=await apiFetch("/api/v1/research/candidates",{cache:"no-store"});
 return res.json();
}
export async function getCompany(ticker:string){
 const res=await apiFetch(`/api/v1/research/companies/${encodeURIComponent(ticker)}`,{next:{revalidate:300}});
 if(!res?.ok) return null;
 return res.json();
}
export type AuditLayer={key:string;label:string;companies:number;total:number;coverage_pct:number;status:string};
export type FinancialGap={ticker:string;status:string;ttm_period?:string|null;latest_report?:{period_end:string}|null;missing_fields?:string[]};
export type DataAudit={universe:number;layers:AuditLayer[];missing_price_tickers:string[];notes:string[];financial_checked_at?:string|null;financial_quality?:{universe_checked:number;current_ttm:number;current_complete:number;field_coverage:Record<string,number>;status_counts:Record<string,number>}|null;financial_gaps?:FinancialGap[]};
export async function getDataAudit():Promise<DataAudit>{
 const res=await apiFetch("/api/v1/research/data-audit",{cache:"no-store"});
 return res.json();
}

export async function getSignals(){
 const res=await apiFetch("/api/v1/research/signals",{cache:"no-store"}); return res.json();
}
export async function getScorecard(){
 const res=await apiFetch("/api/v1/research/scorecard",{cache:"no-store"}); return res.json();
}

export async function getPortfolioComparison(){
 const res=await apiFetch("/api/v1/research/portfolio-comparison",{cache:"no-store"}); return res.json();
}

export async function getSystemHealth(){
 const res=await apiFetch("/api/v1/research/system-health",{cache:"no-store"});
 return res.json();
}
