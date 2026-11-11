import {NextResponse} from "next/server";
export const dynamic="force-dynamic";
export async function GET(){
 const base=process.env.PAPER_API_URL, token=process.env.PAPER_API_TOKEN;
 if(!base||!token) return NextResponse.json({configured:false,error:"Backend environment variables are not configured."},{status:503});
 const r=await fetch(base.replace(/\/$/,"")+"/api/snapshot",{headers:{Authorization:"Bearer "+token},cache:"no-store"});
 return new NextResponse(await r.text(),{status:r.status,headers:{"content-type":"application/json"}});
}
