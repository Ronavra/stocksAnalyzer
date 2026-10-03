import type {DataAudit} from "@/lib/api";

const fields:Record<string,string>={revenue:"Revenue",net_income:"Net income",eps_diluted:"Diluted EPS",operating_income:"Operating income",free_cash_flow:"Free cash flow",cash:"Cash",total_debt:"Reported debt",shares_outstanding:"Shares outstanding"};
const statuses:Record<string,string>={current:"Latest TTM · missing fields",filing_check_unavailable:"Filing verification unavailable",filing_check_failed:"Filing verification failed",extraction_behind_latest_filing:"Latest filing not extracted",insufficient_ttm_history:"Insufficient TTM history",ttm_behind_latest_filing:"TTM behind latest filing",ttm_period_old:"TTM older than 180 days",missing_cik:"SEC identifier missing",refresh_failed:"Refresh failed"};

export default function FinancialQuality({audit}:{audit:DataAudit}){
 const q=audit.financial_quality;
 const gaps=audit.financial_gaps||[];
 return <section className="panel">
  <div className="panelHead"><div><p className="eyebrow">FINANCIAL FRESHNESS</p><h2>Latest filings and missing financial fields</h2></div><p className="muted">Checked: {audit.financial_checked_at||"Not verified yet"}</p></div>
  {!q?<p className="muted">A full SEC refresh is required to verify TTM against each company&apos;s latest official filing.</p>:<>
   <div className="definitions"><div><b>Latest TTM verified</b><span>{q.current_ttm} / {q.universe_checked} companies · matches latest filing and period is within 180 days</span></div><div><b>All eight fields available in latest TTM</b><span>{q.current_complete} / {q.universe_checked} companies</span></div></div>
   <div className="coverageGrid">{Object.entries(q.field_coverage).map(([key,count])=><div className="coverageCard" key={key}><div><b>{fields[key]||key}</b><span>{count} / {q.universe_checked} companies · latest extracted TTM</span></div></div>)}</div>
   <p className="muted">Retrieval success, filing freshness and field completeness are separate checks. Missing values remain unavailable; the eight fields are a generic inventory and may not suit every sector. Older annual reports can still be the latest official filing.</p>
   {gaps.length>0&&<details><summary>{gaps.length} companies with a freshness or field gap</summary><div className="tableWrap"><table><thead><tr><th>Ticker</th><th>Check</th><th>TTM period</th><th>Latest filing period</th><th>Missing fields</th></tr></thead><tbody>{gaps.map(g=><tr key={g.ticker}><td>{g.ticker}</td><td>{statuses[g.status]||g.status}</td><td>{g.ttm_period||"—"}</td><td>{g.latest_report?.period_end||"—"}</td><td>{(g.missing_fields||[]).map(k=>fields[k]||k).join(", ")||"—"}</td></tr>)}</tbody></table></div></details>}
  </>}
 </section>;
}
