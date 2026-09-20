"use client";

import {useEffect,useState} from "react";
import Link from "next/link";

type Stock={ticker:string;company:string;sector:string|null};
const API_URL=process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export default function SearchBar({stocks}:{stocks:Stock[]}){
 const [q,setQ]=useState(""); const [results,setResults]=useState<Stock[]>([]);
 useEffect(()=>{
  const s=q.trim(); if(!s){setResults([]);return}
  const local=stocks.filter(x=>x.ticker.toLowerCase().includes(s.toLowerCase())||x.company.toLowerCase().includes(s.toLowerCase())).slice(0,8);
  setResults(local);
  const timer=setTimeout(async()=>{
   try{
    const res=await fetch(`${API_URL}/api/v1/research/companies-search?q=${encodeURIComponent(s)}`);
    if(res.ok) setResults(await res.json());
   }catch{}
  },180);
  return ()=>clearTimeout(timer);
 },[q,stocks]);
 return <div className="stockSearch">
  <input value={q} onChange={e=>setQ(e.target.value)} placeholder="Search any S&P 500 ticker or company…" aria-label="Search stocks" autoComplete="off" />
  {q.trim()&&<div className="searchResults">
   {results.length?results.map(x=><Link key={x.ticker} href={`/company/${x.ticker}`} onClick={()=>setQ("")}>
    <b>{x.ticker}</b><span>{x.company}</span><small>{x.sector||"S&P 500"}</small>
   </Link>):<p>No matching stocks</p>}
  </div>}
 </div>;
}
