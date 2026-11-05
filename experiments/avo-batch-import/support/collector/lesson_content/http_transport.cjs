// Temporary feasibility probe: reads the isolated mv-centr browser profile locally.
// Authentication stays in memory and is sent only to the same AVO origin over HTTPS.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {execFileSync} = require('node:child_process');
const {DatabaseSync} = require('node:sqlite');
const root=path.resolve(__dirname,'../../exports/lesson-content');
const profile=path.join(root,'private-browser-profiles','mv-centr');
const host='shop.mv-centr.ru';

function cookiesForSource() {
  const keyScript = `$state=Get-Content -LiteralPath (Join-Path $env:AVO_COLLECTOR_PROFILE 'Local State') -Raw | ConvertFrom-Json
$blob=[Convert]::FromBase64String($state.os_crypt.encrypted_key)
Add-Type -AssemblyName System.Security
$key=[Security.Cryptography.ProtectedData]::Unprotect($blob[5..($blob.Length-1)],$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
[Convert]::ToBase64String($key)`;
  let key;
  try {key=Buffer.from(execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command','-'],{input:keyScript,encoding:'utf8',windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,AVO_COLLECTOR_PROFILE:profile}}).trim(),'base64');}
  catch (_) {throw Error('key_process_failed');}
  if(key.length!==32)throw Error('key_unavailable');
  const db=new DatabaseSync(path.join(profile,'Default','Network','Cookies'),{readOnly:true});
  try {
    const version=Number(db.prepare("select value from meta where key='version'").get().value);
    const statement=db.prepare('select host_key,name,path,is_secure,expires_utc,encrypted_value from cookies');
    statement.setReadBigInts(true);
    const rows=statement.all();
    const cookies=[];
    for(const row of rows){
      const domain=row.host_key.replace(/^\./,'');
      if(!(host===domain || (row.host_key.startsWith('.')&&host.endsWith('.'+domain))))continue;
      const data=Buffer.from(row.encrypted_value);
      if(data.subarray(0,3).toString()!=='v10'||data.length<31)throw Error('cookie_format_unavailable');
      const cipher=crypto.createDecipheriv('aes-256-gcm',key,data.subarray(3,15));
      cipher.setAuthTag(data.subarray(-16));
      let plain=Buffer.concat([cipher.update(data.subarray(15,-16)),cipher.final()]);
      if(version>=24){
        const expected=crypto.createHash('sha256').update(row.host_key).digest();
        if(plain.length<32 || !crypto.timingSafeEqual(plain.subarray(0,32),expected))throw Error('cookie_host_mismatch');
        plain=plain.subarray(32);
      }
      const value=plain.toString('utf8');
      if(/[\r\n;]/.test(value)||/[\r\n;=]/.test(row.name))throw Error('invalid_cookie');
      const expiry=Number(row.expires_utc);
      if(expiry && expiry/1000-11644473600000<Date.now())continue;
      cookies.push({name:row.name,value,path:row.path||'/'});
    }
    return cookies;
  } finally { db.close();key.fill(0); }
}

async function getHtml(url,cookies){
  const u=new URL(url);
  if(u.protocol!=='https:'||u.hostname!==host||u.port)throw Error('wrong_origin');
  const cookie=cookies.filter(c=>u.pathname===c.path || u.pathname.startsWith(c.path.endsWith('/')?c.path:c.path+'/')).sort((a,b)=>b.path.length-a.path.length).map(c=>c.name+'='+c.value).join('; ');
  const response=await fetch(u,{headers:{cookie},redirect:'manual',signal:AbortSignal.timeout(45000)});
  if(response.status!==200)throw Error('http_status_'+response.status);
  if(!/^text\/html\b/i.test(response.headers.get('content-type')||''))throw Error('unexpected_content_type');
  const chunks=[];let size=0;
  for await(const part of response.body){size+=part.length;if(size>32*1024*1024){await response.body.cancel().catch(()=>{});throw Error('source_size');}chunks.push(part);}
  return Buffer.concat(chunks).toString('utf8');
}
module.exports={cookiesForSource,getHtml};
