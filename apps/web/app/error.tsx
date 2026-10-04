"use client";
import Link from "next/link";
export default function ErrorPage({reset}:{error:Error;reset:()=>void}){
 return <main><section className="panel" role="alert"><h1>Data could not be loaded</h1><p>The data service is temporarily unavailable. Retry or return to the dashboard to check its status.</p><button type="button" onClick={reset}>Try again</button> <Link href="/">Dashboard</Link></section></main>;
}
