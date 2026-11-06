// Refresh only the three owner-corrected MV-Centr lessons. Authentication and
// page content stay in memory and diagnostics never contain private URLs.
const path = require('node:path')
const { spawnSync } = require('node:child_process')
const root = path.resolve(__dirname, '../../..')
const { cookiesForSource, getHtml } = require(path.join(root, 'collector/lesson_content/http_transport.cjs'))
async function main() {
  const cookies = cookiesForSource()
  let errors = 0
  for (const lesson of [8580,8581,8582]) {
    const html = await getHtml(`https://shop.mv-centr.ru/shop/training/traininglessons/admin/update?id=${lesson}&lg=ru`, cookies)
    const p = spawnSync('py', ['-3.12', path.join(__dirname,'refresh_reviewed_video.py')], {
      input:JSON.stringify({course_id:889,lesson_id:lesson,html}), encoding:'utf8', windowsHide:true,
      maxBuffer:1024*1024, env:{...process.env,PYTHONUTF8:'1'}
    })
    if (p.stdout) process.stdout.write(p.stdout)
    if (p.status !== 0) errors++
  }
  if (errors) throw Error('refresh_validation_failed')
}
main().catch(() => { console.error('refresh_failed'); process.exitCode=1 })
