export type Candidate = {
  ticker:string; company:string; sector:string; score:number; signal:string; catalyst:string;
  scores:{fundamentals:number;valuation:number;earnings:number;momentum:number;news:number;catalysts:number};
  what_changed:string; market_assumption:string;
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function getCandidates(): Promise<Candidate[]> {
  try {
    const res = await fetch(`${API}/api/v1/research/candidates`, { next: { revalidate: 300 } });
    if (!res.ok) throw new Error("API error");
    return res.json();
  } catch {
    return [];
  }
}

export async function getCompany(ticker:string): Promise<Candidate|null> {
  try {
    const res = await fetch(`${API}/api/v1/research/companies/${ticker}`, { next: { revalidate: 300 } });
    return res.ok ? res.json() : null;
  } catch { return null; }
}
