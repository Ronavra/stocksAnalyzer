export type Candidate = {
  ticker:string; company:string; sector:string|null; signal:string;
  score:number|null; coverage:number|null; catalyst:string|null;
  fundamentals:number|null; valuation:number|null; earnings:number|null;
  pe:number|null; price_to_fcf:number|null; as_of_date:string;
};
const API_URL=process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export async function getCandidates():Promise<Candidate[]>{
  const res=await fetch(`${API_URL}/api/v1/research/candidates`,{next:{revalidate:300}});
  if(!res.ok) throw new Error("Failed to load research candidates");
  return res.json();
}
export async function getCompany(ticker:string){
  const res=await fetch(`${API_URL}/api/v1/research/companies/${ticker}`,{next:{revalidate:300}});
  if(!res.ok) throw new Error("Failed to load company research");
  return res.json();
}
