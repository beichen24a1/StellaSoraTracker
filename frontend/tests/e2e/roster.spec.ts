import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'

const frontend = path.resolve(import.meta.dirname, '../..')
const base = path.resolve(frontend, '../build/electron-e2e')

test('roster follows account switches outside its route and never borrows another UID cache', async () => {
  fs.mkdirSync(base, { recursive: true })
  const fixture = fs.mkdtempSync(path.join(base, 'roster-'))
  const output = path.join(fixture, '中文 空格 数据')
  fs.mkdirSync(output)
  const uids = ['100000001', '100000002', '100000003']
  const labels = ['账号 A', '账号 B', '账号 C']
  fs.writeFileSync(path.join(output, 'accounts.json'), JSON.stringify({ active: uids[0], accounts: uids.map((uid, index) => ({ key: uid, uid, name: labels[index] })) }))
  for (const uid of uids) {
    fs.mkdirSync(path.join(output, 'accounts', uid), { recursive: true })
    fs.writeFileSync(path.join(output, `${uid}.json`), JSON.stringify({ version: 1, uid, categories: { '1': [{ Gid: 10162, Time: 1792700000, Ids: [103] }] } }))
  }
  for (const [index, uid] of uids.slice(0, 2).entries()) {
    fs.writeFileSync(path.join(output, `${uid}_roster.json`), JSON.stringify({ version: 1, uid, updatedAt: new Date().toISOString(), characters: [
      { id: 130, name: `${labels[index]}的多娜`, level: 90 - index * 10, advance: 8, favorite: true,
        // Old/incomplete nested cache fields must be normalized before rendering dialogs.
        skills: [1, 1, 10, 8, 1], potentials: [1], emblems: [
          { slot: 1, name: '保卫者尖章', icon: 'Equipment/103/103', desc: '闪烁着守护力量的尖章，是旅人完成过帝国卫队委托的优秀证明。', active: true,
            attrs: [{ attrId: 804, value: 0.15, cfgValue: 1500, name: '暴击率' }] },
          { slot: 2, name: '旧缓存纹章', active: true },
        ] },
    ] }))
  }
  const protectedFiles = uids.map(uid => `${uid}.json`).concat(uids.slice(0, 2).map(uid => `${uid}_roster.json`))
  const hashes = () => protectedFiles.map(file => createHash('sha256').update(fs.readFileSync(path.join(output, file))).digest('hex'))
  const before = hashes()
  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(fixture, 'profile'), STELLA_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.NODE_OPTIONS
  const launch = () => electron.launch({ executablePath: process.env.STELLA_ELECTRON_BIN || path.join(frontend, 'node_modules/electron/dist/electron.exe'), args: ['--no-sandbox', '.'], cwd: frontend, env })
  let desktop = await launch()
  try {
    let page = await desktop.firstWindow()
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.getByRole('link', { name: '角色', exact: true }).click()
    await expect(page.locator('.roster-card')).toContainText('账号 A的多娜')
    await page.locator('.roster-card .card-head').click()
    await expect(page.getByRole('dialog')).toContainText('旧缓存纹章')
    await expect(page.getByRole('dialog')).toContainText('暴击率 15%')
    await expect(page.getByRole('dialog')).not.toContainText('闪烁着守护力量')
    const thumb = page.getByRole('dialog').locator('.emblem-thumbnail img')
    await expect(thumb).toHaveAttribute('src', 'app://assets/emblems/301.png')
    await expect.poll(() => thumb.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
    await page.screenshot({ path: path.join(base, 'roster-emblem-thumbnails-light.png'), animations: 'disabled' })
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    await page.locator('.roster-card .slot').first().click()
    await expect(page.getByRole('dialog')).toContainText('保卫者尖章')
    await expect(page.getByRole('dialog')).not.toContainText('闪烁着守护力量')
    await expect.poll(() => page.getByRole('dialog').locator('.emblem-thumbnail img').evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click()
    async function switchTo(index: number) {
      await page.getByRole('link', { name: '数据与设置', exact: true }).click()
      await page.locator('.account-select .ant-select-selector').click()
      await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: labels[index] }).click()
      await expect.poll(async () => (await page.evaluate(() => window.stella.request('app.state'))).activeAccount).toBe(uids[index])
      await page.getByRole('link', { name: '角色', exact: true }).click()
    }
    await switchTo(1)
    await expect(page.locator('.roster-card')).toContainText('账号 B的多娜')
    await expect(page.locator('.roster-meta')).toContainText(uids[1]!)
    await switchTo(2)
    await expect(page.locator('.roster-card')).toHaveCount(0)
    await expect(page.getByRole('heading', { name: '还没有角色数据' })).toBeVisible()
    await expect(page.locator('.roster-meta')).toContainText(uids[2]!)
    expect(errors).toEqual([])
    await desktop.close()
    desktop = await launch()
    page = await desktop.firstWindow()
    page.on('pageerror', error => errors.push(error.message))
    await page.getByRole('link', { name: '角色', exact: true }).click()
    await expect(page.locator('.roster-card')).toHaveCount(0)
    await switchTo(0)
    await expect(page.locator('.roster-card')).toContainText('账号 A的多娜')
    await page.getByRole('link', { name: '活动日历', exact: true }).click()
    await expect(page.getByRole('heading', { name: '活动日历', exact: true })).toBeVisible()
    expect(hashes()).toEqual(before)
    expect(errors).toEqual([])
    await page.screenshot({ path: path.join(base, 'roster-calendar-preserved.png'), animations: 'disabled' })
  } finally { await desktop.close() }
})
