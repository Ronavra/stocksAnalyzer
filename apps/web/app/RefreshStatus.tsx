"use client";
import {useEffect,useState,useTransition} from "react";
import {useRouter} from "next/navigation";

export default function RefreshStatus(){
 const router=useRouter(); const [pending,startTransition]=useTransition();
 const [checked,setChecked]=useState<string|null>(null);
 function refresh(){startTransition(()=>{router.refresh();setChecked(new Date().toLocaleTimeString());});}
 useEffect(()=>{
  const timer=setInterval(()=>{if(document.visibilityState==="visible"&&navigator.onLine) refresh();},300000);
  return ()=>clearInterval(timer);
 },[router]);
 return <p className="muted"><button type="button" onClick={refresh} disabled={pending}>{pending?"Refreshing…":"Refresh data"}</button> · Checks for updated data every 5 minutes while this page is visible.{checked&&` Last requested: ${checked}`}</p>;
}
