import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const frontend = path.resolve(import.meta.dirname, '../..')
const base = path.resolve(frontend, '../build/electron-e2e')
function fixture(name: string) {
  fs.mkdirSync(base, { recursive: true })
  const root = fs.mkdtempSync(path.join(base, name+'-'))
  const output = path.join(root, '中文 数据')
  fs.mkdirSync(output)
  const env = { ...process.env, STELLA_OUTPUT: output, STELLA_PROFILE: path.join(root, 'profile'), STELLA_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE; delete env.NODE_OPTIONS; delete env.VITE_DEV_SERVER_URL
  return { root, output, env }
}
const launch = (env: NodeJS.ProcessEnv) => electron.launch({ executablePath: path.join(frontend, 'node_modules/electron/dist/electron.exe'), args: ['--no-sandbox', '.'], cwd: frontend, env })

test('exit prompts are custom, deduplicated and recheck data safety before quitting', async () => {
  const { output, env } = fixture('close-dialogs')
  Object.assign(env, { STELLA_E2E_CLOSE: '1', PYTHONPATH: path.join(frontend, 'tests/fixtures') })
  fs.writeFileSync(path.join(output, 'close-case.txt'), 'busy')
  const desktop = await launch(env)
  try {
    const page = await desktop.firstWindow()
    await expect(page.getByRole('heading', { name: '主页', exact: true })).toBeVisible()
    await desktop.evaluate(({ dialog }) => { dialog.showMessageBox = async () => { throw new Error('Native message dialog must not be used') } })
    const close = () => desktop.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]!.close())
    await close()
    await expect(page.getByRole('dialog')).toContainText('正在完成操作')
    await close()
    await expect(page.getByRole('dialog')).toHaveCount(1)
    await page.getByRole('button', { name: '查看任务与日志', exact: true }).click()
    await expect(page.locator('.ant-drawer')).toBeVisible()
    await page.locator('.ant-drawer-close').click()
    fs.writeFileSync(path.join(output, 'close-case.txt'), 'waiting')
    await close()
    await expect(page.getByRole('dialog')).toContainText('后台还未结束')
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    fs.writeFileSync(path.join(output, 'close-case.txt'), 'update')
    await close()
    await expect(page.getByRole('dialog')).toContainText('更新还在下载，要退出吗')
    await page.getByRole('button', { name: '继续下载', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    expect(desktop.windows()).toHaveLength(1)
    await close()
    await expect(page.getByRole('dialog')).toContainText('更新还在下载，要退出吗')
    fs.writeFileSync(path.join(output, 'close-case.txt'), 'busy')
    await page.getByRole('button', { name: '停止并退出', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('正在完成操作')
    expect(desktop.windows()).toHaveLength(1)
    await page.getByRole('button', { name: '返回软件', exact: true }).click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    fs.writeFileSync(path.join(output, 'close-case.txt'), 'update')
    await close()
    await page.screenshot({ path: path.join(base, 'exit-custom-light.png'), animations: 'disabled' })
    const ended = desktop.waitForEvent('close')
    await page.getByRole('button', { name: '停止并退出', exact: true }).click()
    await ended
  } finally { await desktop.close().catch(() => {}) }
})

test('startup failure uses a standalone recovery design, then retries into the real app', async () => {
  const { output, env } = fixture('recovery')
  fs.writeFileSync(path.join(output, 'ui_settings.json'), JSON.stringify({ color_mode: 'dark' }))
  Object.assign(env, { VITE_DEV_SERVER_URL: 'http://127.0.0.1:1' })
  const desktop = await launch(env)
  try {
    await expect.poll(() => desktop.windows().filter(page => page.url().startsWith('data:text/html')).length).toBe(1)
    const recovery = desktop.windows().find(page => page.url().startsWith('data:text/html'))!
    await expect(recovery.getByRole('heading', { name: '启动未完成', exact: true })).toBeVisible()
    expect(await recovery.evaluate(() => typeof (window as any).stella)).toBe('undefined')
    expect(await recovery.evaluate(() => typeof (window as any).require)).toBe('undefined')
    expect(await recovery.evaluate(async () => { try { await (window as any).stellaRecovery.perform('shell.execute'); return false } catch { return true } })).toBe(true)
    await desktop.evaluate(({ clipboard }) => { clipboard.writeText = value => { (globalThis as any).recoveryCopy = value } })
    await recovery.getByRole('button', { name: '复制详情', exact: true }).click()
    await expect(recovery.getByRole('status')).toContainText('错误详情已复制')
    expect(await desktop.evaluate(() => (globalThis as any).recoveryCopy)).toContain('日志目录')
    await recovery.screenshot({ path: path.join(base, 'startup-recovery-dark.png'), animations: 'disabled' })
    await desktop.evaluate(() => { delete process.env.VITE_DEV_SERVER_URL })
    await recovery.getByRole('button', { name: '重试启动', exact: true }).click()
    await expect.poll(() => desktop.windows().filter(page => page.url().startsWith('app://ui')).length).toBe(1)
    const app = desktop.windows().find(page => page.url().startsWith('app://ui'))!
    await expect(app.getByRole('heading', { name: '主页', exact: true })).toBeVisible()
    await expect.poll(() => desktop.windows().filter(page => page.url().startsWith('data:text/html')).length).toBe(0)
  } finally { await desktop.close() }
})
