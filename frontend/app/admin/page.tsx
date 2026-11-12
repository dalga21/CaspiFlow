import {cookies} from 'next/headers';
import {redirect} from 'next/navigation';
import AdminConsole from './AdminConsole';
export const dynamic='force-dynamic';
export default async function AdminPage(){
 const token=(await cookies()).get('caspiflow_admin')?.value;
 let authenticated=false;
 if(token&&process.env.CUSTOMS_API_KEY){try{
  const response=await fetch(`${process.env.API_URL||'http://127.0.0.1:8000'}/admin/session`,{headers:{'X-API-Key':process.env.CUSTOMS_API_KEY,Cookie:`caspiflow_admin=${token}`},cache:'no-store',signal:AbortSignal.timeout(5000)});
  authenticated=response.ok;
 }catch{authenticated=false;}}
 if(!authenticated)redirect('/admin/login');
 return <AdminConsole/>;
}
