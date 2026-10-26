import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'

const frontend = path.resolve(import.meta.dirname, '../..')
const outputBase = path.resolve(frontend, '../build/electron-e2e')
fs.mkdirSync(outputBase, { recursive: true })

test('real Python engine, all five pages, two themes and account safety', async () => {
  const fixture = fs.mkdtempSync(path.join(outputBase, 'case-'))
  const output = path.join(fixture, '中文 空格 数据')
  fs.mkdirSync(output)
  const uid = '100000001'
  const categories = {
    '1': [{ Gid: 10162, Time: 1792700000, Ids: [103, 162, 103, 110] }],
    '3': [{ Gid: 20162, Time: 1792701000, Ids: [211001, 214066] }],
    '6': [{ Gid: 1001, Time: 1792702000, Ids: [162, 103] }],
  }
  fs.writeFileSync(path.join(output, `${uid}.json`), JSON.stringify({ version: 1, uid, categories }))
  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(fixture, 'profile'), STELLA_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.NODE_OPTIONS
  const desktop = await electron.launch({ executablePath: process.env.STELLA_ELECTRON_BIN || path.join(frontend,'node_modules/electron/dist/electron.exe'), args: ['--no-sandbox', '.'], cwd: frontend, env })
  const page = await desktop.firstWindow()
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    await expect(page.getByRole('heading', { name: '每一次相遇，都有记录。' })).toBeVisible()
    await expect(page.locator('.metric-card').first()).toContainText('8')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    await expect(page.locator('.ant-spin-blur')).toHaveCount(0)
    await page.screenshot({ path: path.join(outputBase, 'overview-light.png') })
    await page.getByRole('link', { name: '招募记录', exact: true }).click()
    await expect(page.getByRole('heading', { name: '招募记录', exact: true })).toBeVisible()
    await expect(page.locator('.pool-card')).toHaveCount(3)
    await page.getByText('全部记录', { exact: true }).click()
    await expect(page.locator('.ant-table-tbody .ant-table-row')).toHaveCount(8)
    const anniversary = page.locator('.ant-table-tbody .ant-table-row').filter({ hasText: '星途一载' }).filter({ hasText: '五星' })
    await expect(anniversary.first()).toContainText('—')
    await page.getByRole('link', { name: '数据与设置', exact: true }).click()
    await page.getByLabel('黑色主题').click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect.poll(() => page.locator('input[aria-label="游戏 UID"]').evaluate(element => getComputedStyle(element).backgroundColor)).toBe('rgb(26, 34, 45)')
    await page.screenshot({ path: path.join(outputBase, 'settings-dark.png') })
    await expect(page.getByText('今日运势', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '创建备份', exact: true }).click()
    await expect.poll(() => fs.existsSync(path.join(output, 'backups')) && fs.readdirSync(path.join(output, 'backups')).length).toBe(1)
    await page.getByRole('link', { name: '上传与分享', exact: true }).click()
    await expect(page.locator('.bind-command')).toContainText(uid)
    await expect(page.getByRole('button', { name: '上传到蕾姆', exact: true })).toBeDisabled()
    await page.getByRole('link', { name: '使用说明', exact: true }).click()
    await expect(page.getByRole('heading', { name: '使用说明与风险提示' })).toBeVisible()
    await expect(page.locator('.help-content')).toContainText('MIT')
    await page.setViewportSize({ width: 960, height: 760 })
    await page.screenshot({ path: path.join(outputBase, 'help-dark-960.png') })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    const state = await page.evaluate(() => window.stella.request('app.state'))
    expect(state.summary.pulls).toBe(8)
    expect(state.preferences.color_mode).toBe('dark')
    expect(JSON.parse(fs.readFileSync(path.join(output, `${uid}.json`), 'utf8')).categories).toEqual(categories)
    expect(errors).toEqual([])
    const imported=path.join(fixture,'小号.json')
    fs.writeFileSync(imported,JSON.stringify({uid:'100000002',categories:{'1':[{Gid:10162,Time:1792800000,Ids:[103]}]}}))
    await desktop.evaluate(({dialog},file)=>{dialog.showOpenDialog=async()=>({canceled:false,filePaths:[file]})},imported)
    await page.getByRole('button',{name:/导入文件/}).click()
    await expect.poll(async()=> (await page.evaluate(()=>window.stella.request('app.state'))).summary.uid).toBe('100000002')
    await page.getByRole('link',{name:'数据与设置',exact:true}).click()
    await page.getByRole('button',{name:'重命名',exact:true}).click()
    await page.getByRole('dialog').locator('input').last().fill('测试小号')
    await page.getByRole('dialog').getByRole('button',{name:/保\s*存/,exact:true}).click()
    await expect.poll(async()=> (await page.evaluate(()=>window.stella.request('app.state'))).accounts.find((a:any)=>a.uid==='100000002')?.name).toBe('测试小号')
    await page.getByRole('button',{name:/^删\s*除$/}).click()
    await page.getByRole('button',{name:'确认删除',exact:true}).click()
    await expect.poll(()=>fs.existsSync(path.join(output,'100000002.json'))).toBe(false)
    expect(fs.readdirSync(path.join(output,'accounts')).some(name=>name.includes('.deleted_'))).toBe(true)
    const dropped=path.join(fixture,'拖放记录.json')
    fs.writeFileSync(dropped,JSON.stringify({uid,categories:{'1':[{Gid:10162,Time:1792900000,Ids:[103,103]}]}}))
    await page.evaluate(()=>{const input=document.createElement('input');input.type='file';input.id='test-native-file';document.body.append(input)})
    await page.locator('#test-native-file').setInputFiles(dropped)
    await page.evaluate(()=>{const input=document.querySelector<HTMLInputElement>('#test-native-file')!;const data=new DataTransfer();for(const file of input.files!)data.items.add(file);document.querySelector('.desktop')!.dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:data}));input.remove()})
    await expect.poll(async()=> (await page.evaluate(()=>window.stella.request('app.state'))).summary.pulls).toBe(10)
    await expect.poll(()=>fs.readdirSync(path.join(output,'backups')).length).toBeGreaterThan(1)
    await expect.poll(async()=> (await page.evaluate(()=>window.stella.request('app.state'))).busy).toBe(false)
    const beforeRestart=fs.readFileSync(path.join(output,`${uid}.json`),'utf8')
    const enginePid=await desktop.evaluate(()=>{
      const handles=(process as any)._getActiveHandles()
      return handles.find((handle:any)=>typeof handle.pid==='number' && /python\.exe$/i.test(handle.spawnfile || ''))?.pid
    })
    expect(enginePid).toBeTruthy()
    process.kill(enginePid)
    await expect(page.getByRole('button',{name:'重新连接',exact:true})).toBeVisible()
    await page.getByRole('button',{name:'重新连接',exact:true}).click()
    await expect(page.locator('.connection-error')).toHaveCount(0)
    expect((await page.evaluate(()=>window.stella.request('app.state'))).summary.pulls).toBe(10)
    expect(fs.readFileSync(path.join(output,`${uid}.json`),'utf8')).toBe(beforeRestart)
    expect(errors).toEqual([])
  } finally { await desktop.close() }
})
