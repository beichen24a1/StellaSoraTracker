import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const frontend = path.resolve(import.meta.dirname, '../..')
const outputBase = path.resolve(frontend, '../build/electron-e2e')
fs.mkdirSync(outputBase, { recursive: true })

test('affinity lives on its own page and its own file, separate from the gacha archive', async () => {
  const fixture = fs.mkdtempSync(path.join(outputBase, 'affinity-'))
  const output = path.join(fixture, 'data')
  const uid = '100000001'
  // 主归档是 <UID>.json; 好感度单独存在 <UID>_affinity.json, 并在页面显示对应 UID
  fs.mkdirSync(path.join(output, 'accounts', uid), { recursive: true })
  const categories = { '1': [{ Gid: 10162, Time: 1792700000, Ids: [103, 162] }] }
  const archive = path.join(output, `${uid}.json`)
  fs.writeFileSync(archive, JSON.stringify({ version: 1, uid, categories }))
  const affinityFile = path.join(output, `${uid}_affinity.json`)
  fs.writeFileSync(affinityFile, JSON.stringify({
    version: 1,
    uid,
    updatedAt: '2026-10-27T12:00:00+08:00',
    entries: [
      { id: 156, name: '小禾', level: 65, exp: 6040, need: 33100, ratio: 0.1825, favorite: true },
      { id: 130, name: '多娜', level: 12, exp: 1575, need: 2000, ratio: 0.7875, favorite: false },
      { id: 103, name: '琥珀', level: 4, exp: 650, need: 500, ratio: 1, favorite: false },
    ],
  }))

  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(fixture, 'profile'), STELLA_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.NODE_OPTIONS
  const desktop = await electron.launch({
    executablePath: process.env.STELLA_ELECTRON_BIN || path.join(frontend, 'node_modules/electron/dist/electron.exe'),
    args: ['--no-sandbox', '.'], cwd: frontend, env,
  })
  const page = await desktop.firstWindow()
  try {
    await expect(page.getByRole('link', { name: '好感度', exact: true })).toBeVisible()
    await page.getByRole('link', { name: '好感度', exact: true }).click()

    await expect(page.getByRole('heading', { name: '旅人好感度', exact: true })).toBeVisible()
    const first = page.locator('.affinity-card').filter({ hasText: '小禾' })
    await expect(first).toContainText('Lv.65')
    await expect(first).toContainText('6,040 / 33,100')
    await expect(page.locator('.affinity-card')).toHaveCount(3)

    // 四星角色也有随包头像(不是只显示首字占位)
    const amber = page.locator('.affinity-card').filter({ hasText: '琥珀' })
    await expect.poll(() => amber.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)

    // 界面在 /affinity, 抽卡页仍是独立路由
    expect(await page.evaluate(() => location.hash)).toBe('#/affinity')

    // 页面显示这份好感度对应的 UID
    await expect(page.locator('.meta-note')).toContainText(uid)

    // 好感度数据在 <UID>_affinity.json 里; 抽卡归档保持原样, 没有混入好感度字段
    const savedArchive = JSON.parse(fs.readFileSync(archive, 'utf8'))
    expect(savedArchive).toEqual({ version: 1, uid, categories })
    const savedAffinity = JSON.parse(fs.readFileSync(affinityFile, 'utf8'))
    expect(savedAffinity.uid).toBe(uid)
    expect(savedAffinity.entries).toHaveLength(3)

    await page.screenshot({ path: path.join(outputBase, 'affinity-page.png'), fullPage: true })
  } finally {
    await desktop.close()
  }
})

test('hhmx imports both saved datasets and automatically uploads only for a bound UID', async () => {
  const fixture = fs.mkdtempSync(path.join(outputBase, 'hhmx-'))
  const output = path.join(fixture, 'data')
  const uid = '100000001'
  fs.mkdirSync(output)
  fs.writeFileSync(path.join(output, `${uid}.json`), JSON.stringify({
    version: 1, uid, categories: { '1': [{ Gid: 10162, Time: 1792700000, Ids: [103] }] },
  }))
  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(fixture, 'profile'),
    STELLA_E2E_HHMX: '1', PYTHONPATH: path.join(frontend, 'tests/fixtures') }
  delete env.STELLA_OFFLINE
  delete env.ELECTRON_RUN_AS_NODE
  delete env.NODE_OPTIONS
  const desktop = await electron.launch({
    executablePath: process.env.STELLA_ELECTRON_BIN || path.join(frontend, 'node_modules/electron/dist/electron.exe'),
    args: ['--no-sandbox', '.'], cwd: frontend, env,
  })
  try {
    await desktop.evaluate(({ session }) => {
      const state = { uids: ['100000002'], posts: [] as any[] }
      ;(globalThis as any).hhmxFixture = state
      session.fromPartition('persist:hhmx-sync').protocol.handle('https', async request => {
        const url = new URL(request.url)
        if (url.origin !== 'https://hhmx.cn') return new Response(null, { status: 404 })
        if (url.pathname === '/') return new Response('<h1>账号页面</h1>', { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
        if (url.pathname === '/api/me') {
          return Response.json({ user: { id: 5 }, uids: state.uids })
        }
        if (request.method === 'POST' && url.pathname === '/api/uids/100000001/import') {
          const { documents } = await request.json()
          state.posts.push(documents)
          return Response.json({
            affinity: documents.filter((item: any) => item.name.endsWith('_affinity.json')).length,
            roster: documents.filter((item: any) => item.name.endsWith('_roster.json')).length,
            warnings: [],
          })
        }
        return new Response(null, { status: 404 })
      })
    })
    const page = await desktop.firstWindow()
    const posts = () => desktop.evaluate(() => (globalThis as any).hhmxFixture.posts)
    await page.getByRole('link', { name: '上传与分享', exact: true }).click()
    const read = (method: string) => page.evaluate(name => window.stella.request(name, { pid: 12 }), method)
    await read('affinity.read')
    await expect.poll(() => fs.existsSync(path.join(output, `${uid}_affinity.json`))).toBe(true)
    expect(await posts()).toEqual([])

    await page.getByRole('switch', { name: '自动同步好感度和角色数据到 hhmx.cn' }).click()
    await expect(page.getByRole('switch', { name: '自动同步好感度和角色数据到 hhmx.cn' })).toHaveAttribute('aria-checked', 'true')
    await read('roster.read')
    await expect(page.getByText(`请先在应用内的 hhmx.cn 账号页面绑定 UID ${uid}，然后重试同步`)).toBeVisible()
    expect(await posts()).toEqual([])

    const opened = desktop.waitForEvent('window')
    await page.getByRole('button', { name: '打开 hhmx.cn 账号页面' }).click()
    const accountPage = await opened
    await expect(accountPage.getByRole('heading', { name: '账号页面' })).toBeVisible()
    expect(await accountPage.evaluate(() => typeof window.stella)).toBe('undefined')
    await accountPage.close()
    await desktop.evaluate(() => { (globalThis as any).hhmxFixture.uids = ['100000001'] })
    await page.getByRole('button', { name: '立即同步' }).click()
    await expect.poll(async () => (await posts()).length).toBe(1)
    await read('affinity.read')
    await read('roster.read')
    await expect.poll(async () => (await posts()).length).toBe(3)
    const documents = await posts()
    expect(documents[0].map((item: any) => item.name)).toEqual([`${uid}_affinity.json`, `${uid}_roster.json`])
    expect(documents.slice(1).flat().map((item: any) => item.name).sort()).toEqual([`${uid}_affinity.json`, `${uid}_roster.json`])
    expect(documents.flat().every((doc: any) => doc.data.uid === uid && !doc.data.path && !doc.data.categories)).toBe(true)
  } finally {
    await desktop.close()
  }
})
