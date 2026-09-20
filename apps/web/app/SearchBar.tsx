"use client";

import {useMemo,useState} from "react";
import Link from "next/link";

type Stock={ticker:string;company:string;sector:string|null};

export default function SearchBar({stocks}:{stocks:Stock[]}){
 const [q,setQ]=useState("");
 const results=useMemo(()=>{
  const s=q.trim().toLowerCase();
  if(!s) return [];
  return stocks.filter(x=>x.ticker.toLowerCase().includes(s)||x.company.toLowerCase().includes(s)).slice(0,8);
 },[q,stocks]);
 return <div className="stockSearch">
  <input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search by ticker or company name…" aria-label="Search stocks" />
  {q.trim()&&<div className="searchResults">
   {results.length?results.map(x=><Link key={x.ticker} href={`/company/${x.ticker}`} onClick={()=>setQ("")}>
    <b>{x.ticker}</b><span>{x.company}</span><small>{x.sector||"S&P 500"}</small>
   </Link>):<p>No matching stocks</p>}
  </div>}
 </div>;
}
