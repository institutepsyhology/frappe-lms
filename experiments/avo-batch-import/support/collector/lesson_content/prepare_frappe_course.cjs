// Read the live mv-centr course and send it directly to the local preparer.
const {cookiesForSource,getHtml}=require('./http_transport.cjs');
const {spawnSync}=require('node:child_process');
const path=require('node:path');
async function main(){
  const course=Number(process.argv[2]);
  if(!Number.isSafeInteger(course)||course<1)throw Error('invalid_course');
  const html=await getHtml('https://shop.mv-centr.ru/shop/training/admin/update?id='+course+'&lg=ru',cookiesForSource());
  const p=spawnSync('py',['-3.12',path.join(__dirname,'prepare_frappe_course.py')],{input:JSON.stringify({course_id:course,html}),encoding:'utf8',windowsHide:true,maxBuffer:128*1024*1024,env:{...process.env,PYTHONUTF8:'1'}});
  if(p.stdout)process.stdout.write(p.stdout);
  if(p.status!==0)process.exitCode=1;
}
main().catch(()=>{console.error('source_unavailable');process.exitCode=1});
