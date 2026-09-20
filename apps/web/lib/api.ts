export type Candidate = {
 ticker:string; company:string; sector:string|null; signal:string; score:number|null; coverage:number|null; catalyst:string|null;
 fundamentals:number|null; valuation:number|null; earnings:number|null; pe:number|null; price_to_fcf:number|null; as_of_date:string;
 opportunity_score:number|null; setup_probability_up:number|null; setup_median_return_5d:number|null; setup_sample_size:number|null;
 upside_to_60d_high:number|null; setup_drawdown_60d:number|null; opportunity_reason:string|null; current_price:number|null; price_date:string|null; price_source:string|null;
};
const API_URL=process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export async function getCandidates():Promise<Candidate[]>{const res=await fetch(`${API_URL}/api/v1/research/candidates`,{next:{revalidate:300}});if(!res.ok) throw new Error("Failed to load research candidates");return res.json();}
export async function getCompany(ticker:string){const res=await fetch(`${API_URL}/api/v1/research/companies/${ticker}`,{next:{revalidate:300}});if(!res.ok) throw new Error("Failed to load company research");return res.json();}
