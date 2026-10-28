import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'

const frontend = path.resolve(import.meta.dirname, '../..')
const base = path.resolve(frontend, '../build/electron-e2e')
test('calendar loads cached official events, preserves selection and filters, opens official links and adapts to both themes', async () => {
  fs.mkdirSync(base, { recursive: true })
  const fixture = fs.mkdtempSync(path.join(base, 'calendar-'))
  const output = path.join(fixture, '数据 空格')
  const imageRoot = path.join(output, 'calendar/images')
  fs.mkdirSync(imageRoot, { recursive: true })
  const cover = 'a'.repeat(64)+'.webp'
  fs.writeFileSync(path.join(imageRoot, cover), Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64'))
  const now = Math.floor(Date.now() / 1000)
  const entry = { id: 4983, name: '乘光而起的星之砂', title: '「乘光而起的星之砂」复刻纪念活动说明', kind: 'event',
    startAt: now - 86400, endAt: now + 7 * 86400, startApproximate: false, description: '复刻纪念活动', cover }
  fs.writeFileSync(path.join(output, 'calendar/index.json'), JSON.stringify({ updatedAt: now, items: [entry,
    { ...entry, id: 4700, name: '灾变防线', title: '「灾变防线」活动说明', kind: 'permanent' },
    { ...entry, id: 5000, name: '联合讨伐', title: '「联合讨伐」活动说明', startAt: now + 86400 }] }))
  const archive = path.join(output, '100000001.json')
  fs.writeFileSync(archive, JSON.stringify({ version: 1, uid: '100000001', categories: { '1': [{ Gid: 10162, Time: now, Ids: [103, 162] }] } }))
  const hash = () => createHash('sha256').update(fs.readFileSync(archive)).digest('hex')
  const before = hash()
  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(fixture, 'profile'), STELLA_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.NODE_OPTIONS
  const desktop = await electron.launch({ executablePath: process.env.STELLA_ELECTRON_BIN || path.join(frontend, 'node_modules/electron/dist/electron.exe'), args: ['--no-sandbox', '.'], cwd: frontend, env })
  try {
    await desktop.evaluate(({ shell }) => { (globalThis as any).calendarLinks = []; shell.openExternal = async url => { (globalThis as any).calendarLinks.push(url) } })
    const page = await desktop.firstWindow()
    await page.getByRole('link', { name: '活动日历', exact: true }).click()
    await expect(page.getByRole('heading', { name: '活动日历', exact: true })).toBeVisible()
    await expect(page.locator('.calendar-schedule-card')).toHaveCount(3)
    expect(await page.evaluate(() => Math.abs(document.querySelector('.calendar-main')!.getBoundingClientRect().height - document.querySelector('.calendar-schedule')!.getBoundingClientRect().height))).toBeLessThan(2)
    expect(await page.locator('.calendar-main').evaluate(element => element.getBoundingClientRect().height)).toBeLessThan(1200)
    await expect(page.locator('.calendar-alert')).toContainText('离线模式')
    await expect.poll(() => page.locator('.calendar-hero-image').evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
    await page.getByRole('button', { name: '「灾变防线」活动说明', exact: true }).click()
    await expect(page.locator('.calendar-hero h2')).toHaveText('灾变防线')
    await page.getByRole('button', { name: '查看活动公告' }).click()
    expect(await desktop.evaluate(() => (globalThis as any).calendarLinks)).toEqual(['https://stellasora.yostar.cn/news/4700'])
    await page.getByRole('button', { name: '国服官网', exact: true }).click()
    expect((await desktop.evaluate(() => (globalThis as any).calendarLinks))[1]).toBe('https://stellasora.yostar.cn/')
    await expect(page.getByRole('textbox', { name: '搜索活动' })).toHaveCount(0)
    await page.locator('.calendar-filters .ant-select-selector').click()
    await page.getByText('全部日程', { exact: true }).click()
    await page.getByRole('link', { name: '数据与设置', exact: true }).click()
    await page.getByRole('button', { name: '黑色主题', exact: true }).click()
    await page.getByRole('link', { name: '活动日历', exact: true }).click()
    await expect(page.locator('.calendar-filters')).toContainText('全部日程')
    await expect(page.locator('.calendar-hero h2')).toHaveText('灾变防线')
    await page.screenshot({ path: path.join(base, 'calendar-dark.png'), fullPage: true, animations: 'disabled' })
    await desktop.evaluate(({ BrowserWindow }) => { BrowserWindow.getAllWindows()[0]!.setSize(960, 720) })
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await page.screenshot({ path: path.join(base, 'calendar-small.png'), fullPage: true })
    expect(await page.evaluate(async () => { try { return !(await fetch('app://calendar/index.json')).ok } catch { return true } })).toBe(true)
    expect(await page.evaluate(async () => { try { await window.stella.request('shell.openCalendarArticle', { id: 'https://evil.test' }); return false } catch { return true } })).toBe(true)
    expect(hash()).toBe(before)
    await page.getByRole('button', { name: '刷新活动' }).click()
    await expect(page.locator('.calendar-alert')).toContainText('离线模式')
  } finally { await desktop.close() }
})
