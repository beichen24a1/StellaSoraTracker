import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const frontend = path.resolve(import.meta.dirname, '../..')
const base = path.resolve(frontend, '../build/electron-e2e')
test('home summarizes real cached modules and preserves navigation, themes and account isolation', async () => {
  fs.mkdirSync(base, { recursive: true })
  const fixture = fs.mkdtempSync(path.join(base, 'home-'))
  const output = path.join(fixture, '中文 数据')
  fs.mkdirSync(path.join(output, 'calendar'), { recursive: true })
  const a = '100000001', b = '100000002'
  fs.writeFileSync(path.join(output, 'accounts.json'), JSON.stringify({ active: a, accounts: [a, b].map((uid, index) => ({ key: uid, uid, name: `测试账号 ${index ? 'B' : 'A'}` })) }))
  for (const uid of [a, b]) {
    fs.mkdirSync(path.join(output, 'accounts', uid), { recursive: true })
    fs.writeFileSync(path.join(output, `${uid}.json`), JSON.stringify({ version: 1, uid, categories: uid === a ? { '1': [{ Gid: 10162, Time: 1792700000, Ids: [103, 162, 162, 103] }] } : {} }))
  }
  fs.writeFileSync(path.join(output, `${a}_roster.json`), JSON.stringify({ uid: a, version: 1, characters: [
    { id: 130, name: '多娜', level: 90, advance: 8 }, { id: 103, name: '琥珀', level: 80, advance: 5 }, { id: 156, name: '小禾', level: 70, advance: 4 },
  ] }))
  fs.writeFileSync(path.join(output, `${a}_affinity.json`), JSON.stringify({ uid: a, version: 1, entries: [
    { id: 156, name: '小禾', level: 65, exp: 6040, need: 33100 }, { id: 130, name: '多娜', level: 12, exp: 1500, need: 2000 },
  ] }))
  const now = Date.now() / 1000 | 0
  fs.writeFileSync(path.join(output, 'calendar/index.json'), JSON.stringify({ updatedAt: now, items: [{ id: 499, name: '星塔周年活动', title: '周年活动一览', kind: 'version', startAt: now - 86400, endAt: now + 5 * 86400, startApproximate: false, description: '', cover: '' }] }))
  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(fixture, 'profile'), STELLA_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.NODE_OPTIONS
  const desktop = await electron.launch({ executablePath: path.join(frontend, 'node_modules/electron/dist/electron.exe'), args: ['--no-sandbox', '.'], cwd: frontend, env })
  try {
    const page = await desktop.firstWindow()
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await expect(page.getByRole('heading', { name: '主页', exact: true })).toBeVisible()
    await expect(page.locator('.home-stats>a').nth(0)).toContainText('4')
    await expect(page.locator('.home-stats>a')).toHaveCount(3)
    await expect(page.locator('.home-stats>a').filter({ hasText: '最高好感度' })).toContainText('65')
    await expect(page.locator('.home-five-item')).toHaveCount(2)
    await expect(page.locator('.home-event-cover')).toContainText('星塔周年活动')
    // Click titles and blank card areas, not only the small footer links.
    for (const [selector, heading] of [
      ['.home-recent', '招募记录'], ['.home-collection[data-kind=roster]', '角色数据'],
      ['.home-collection[data-kind=affinity]', '好感度'], ['.home-events', '活动日历'],
    ]) {
      await page.locator(selector!).click({ position: { x: 8, y: 8 } })
      await expect(page.getByRole('heading', { name: heading!, exact: true })).toBeVisible()
      await page.getByRole('link', { name: '主页', exact: true }).click()
    }
    await page.locator('.home-collection[data-kind=roster] .home-card-link').focus()
    await page.keyboard.press('Enter')
    await expect(page.getByRole('heading', { name: '角色数据', exact: true })).toBeVisible()
    await page.getByRole('link', { name: '主页', exact: true }).click()
    await page.screenshot({ path: path.join(base, 'home-light.png'), animations: 'disabled' })
    await page.locator('.home-collection[data-kind=roster] footer a').click()
    await expect(page.getByRole('heading', { name: '角色数据', exact: true })).toBeVisible()
    await page.getByRole('link', { name: '主页', exact: true }).click()
    await page.getByRole('button', { name: '任务与日志', exact: true }).click()
    await expect(page.getByText('任务与日志', { exact: true }).last()).toBeVisible()
    await page.locator('.ant-drawer-close').click()
    await page.getByRole('link', { name: '数据与设置', exact: true }).click()
    await page.getByRole('button', { name: '黑色主题', exact: true }).click()
    await page.getByRole('link', { name: '主页', exact: true }).click()
    await expect(page.locator('.home-collection[data-kind=roster]')).toContainText('多娜')
    await page.screenshot({ path: path.join(base, 'home-dark.png'), animations: 'disabled' })
    await desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.setSize(960, 720))
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: path.join(base, 'home-small.png'), animations: 'disabled' })
    await page.getByRole('link', { name: '数据与设置', exact: true }).click()
    await page.locator('.account-select .ant-select-selector').click()
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: '测试账号 B' }).click()
    await expect.poll(async () => (await page.evaluate(() => window.stella.request('app.state'))).activeAccount).toBe(b)
    await page.getByRole('link', { name: '主页', exact: true }).click()
    await expect(page.locator('.home-passport')).toContainText('测试账号 B')
    await expect(page.locator('.home-collection[data-kind=roster]')).toContainText('还没有角色数据')
    await expect(page.locator('.home-collection[data-kind=affinity]')).toContainText('还没有好感度记录')
    await expect(page.locator('.home-five-item')).toHaveCount(0)
    await expect(page.locator('.home-event-cover')).toContainText('星塔周年活动')
    // The stretched link must not steal the empty-state capture/import buttons.
    await desktop.evaluate(({ dialog }) => {
      ;(dialog as any).__homeImportCount = 0
      dialog.showOpenDialog = async () => { (dialog as any).__homeImportCount++; return { canceled: true, filePaths: [] } }
    })
    await page.locator('.home-empty-actions').getByRole('button', { name: '导入记录', exact: true }).click()
    await expect.poll(() => desktop.evaluate(({ dialog }) => (dialog as any).__homeImportCount)).toBe(1)
    await expect(page.getByRole('heading', { name: '主页', exact: true })).toBeVisible()
    expect(errors).toEqual([])
  } finally { await desktop.close() }
})
