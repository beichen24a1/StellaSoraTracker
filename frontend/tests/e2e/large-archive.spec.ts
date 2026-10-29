import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

test('100,000 records stay paged and searchable in a responsive Electron window', async () => {
  const frontend = path.resolve(import.meta.dirname, '../..')
  const base = path.resolve(frontend, '../build/electron-e2e')
  fs.mkdirSync(base, { recursive: true })
  const fixture = fs.mkdtempSync(path.join(base, 'large-'))
  const output = path.join(fixture, '数据')
  fs.mkdirSync(output)
  const groups = Array.from({ length: 10_000 }, (_, index) => ({
    Gid: 10162, Time: 1792700000 + index, Ids: Array(10).fill(103),
  }))
  fs.writeFileSync(path.join(output, '100000001.json'), JSON.stringify({
    version: 1, uid: '100000001', categories: { '1': groups },
  }))
  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(fixture, 'profile'), STELLA_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  delete env.NODE_OPTIONS
  const desktop = await electron.launch({
    executablePath: path.join(frontend, 'node_modules/electron/dist/electron.exe'),
    args: ['--no-sandbox', '.'], cwd: frontend, env,
  })
  const page = await desktop.firstWindow()
  try {
    await page.getByRole('link', { name: '招募总览', exact: true }).click()
    await expect(page.locator('.metric-card').first()).toContainText('100,000', { timeout: 30000 })
    await page.getByRole('link', { name: '招募记录', exact: true }).click()
    await page.getByText('全部记录', { exact: true }).click()
    await expect(page.locator('.ant-table-tbody .ant-table-row')).toHaveCount(50)
    await expect(page.locator('.records-caption')).toContainText('100,000')
    await page.locator('.ant-pagination-item-2').click()
    await expect(page.locator('.ant-pagination-item-active')).toContainText('2')
    await expect(page.locator('.ant-spin-blur')).toHaveCount(0)
    const search = page.getByLabel('搜索记录')
    await search.fill('没有这个名字')
    // Renderer interaction must remain usable while the Python query runs.
    await expect(search).toHaveValue('没有这个名字')
    await expect(page.locator('.ant-table-tbody .ant-table-row')).toHaveCount(0)
    await expect(page.locator('.records-caption')).toContainText('0 条记录')
    await search.fill('')
    await expect(page.locator('.ant-table-tbody .ant-table-row')).toHaveCount(50)
    const query = await page.evaluate(() => window.stella.request('records.query', { mode: 'all', page: 2, pageSize: 50 }))
    expect(query.total).toBe(100000)
    expect(query.items).toHaveLength(50)
    expect(JSON.stringify(query).length).toBeLessThan(50000)
    const frameTime = await page.evaluate(() => new Promise<number>(resolve => {
      const started = performance.now(); requestAnimationFrame(() => resolve(performance.now() - started))
    }))
    expect(frameTime).toBeLessThan(1000)
    fs.writeFileSync(path.join(base, 'large-archive-result.json'), JSON.stringify({
      records: query.total, pageSize: query.items.length, responseBytes: JSON.stringify(query).length, frameTime,
    }, null, 2))
  } finally { await desktop.close() }
})
