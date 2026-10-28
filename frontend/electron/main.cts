import { app, BrowserWindow, clipboard, dialog, ipcMain, nativeTheme, net, protocol, shell } from 'electron'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { createInterface } from 'node:readline'
import { createHash, randomUUID } from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

// 以管理员身份运行时 Chromium 渲染进程的沙箱会启动失败(launch-failed),
// 本工具只加载本地打包页面、禁用新窗口与外部导航, 关闭沙箱是安全的。
app.commandLine.appendSwitch('no-sandbox')
app.commandLine.appendSwitch('disable-gpu-sandbox')

const frontendRoot = path.resolve(__dirname, '..')
const projectRoot = app.isPackaged ? path.dirname(process.execPath) : path.resolve(frontendRoot, '..')
const appRoot = app.isPackaged ? path.dirname(process.execPath) : projectRoot
const outputRoot = path.resolve(process.env.STELLA_OUTPUT || path.join(appRoot, 'exports'))
const assetsRoot = app.isPackaged ? path.join(process.resourcesPath, 'assets') : path.join(projectRoot, 'assets')
const cacheAssets = path.join(outputRoot, 'assets')
const profileRoot = process.env.STELLA_PROFILE || path.join(appRoot, app.isPackaged ? '.desktop' : 'build/electron-profile')
fs.mkdirSync(profileRoot, { recursive: true })
app.setPath('userData', profileRoot)
app.setName(app.isPackaged ? 'StellaSoraTracker' : 'StellaSoraTracker-Dev')
protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } }])

const methods = new Set([
  'app.state', 'records.query', 'records.capture', 'records.import', 'records.export', 'records.share',
  'accounts.create', 'accounts.switch', 'accounts.rename', 'accounts.remove', 'accounts.merge',
  'uid.save', 'uid.read', 'processes.list', 'server.save', 'preferences.save', 'archive.backup',
  'resources.sync', 'upload.send', 'updates.check', 'updates.download', 'updates.cancel', 'updates.install',
  'affinity.read', 'affinity.load',
  'roster.read', 'roster.load',
])
const tokens = new Map<string, { path: string; kind: 'import' | 'export' }>()
let window: BrowserWindow | null = null
let quitting = false
let uiReady = false
let initialState: any = null

class EngineClient extends EventEmitter {
  child: ChildProcessWithoutNullStreams | null = null
  counter = 0
  pending = new Map<number, { resolve: (value: any) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>()
  start() {
    const executable = app.isPackaged ? path.join(process.resourcesPath, 'engine/StellaSoraEngine.exe') : (process.env.STELLA_PYTHON || path.join(projectRoot, '.venv/Scripts/python.exe'))
    const args = app.isPackaged ? [] : ['-m', 'stellasora_toolkit.desktop_engine']
    fs.mkdirSync(cacheAssets, { recursive: true })
    // Seed bundled images once; future sync writes only this writable cache.
    for (const kind of ['travelers', 'discs']) {
      const source = path.join(assetsRoot, kind)
      const target = path.join(cacheAssets, kind)
      fs.mkdirSync(target, { recursive: true })
      if (fs.existsSync(source)) for (const name of fs.readdirSync(source)) {
        if (/^\d+\.png$/.test(name) && !fs.existsSync(path.join(target, name))) fs.copyFileSync(path.join(source, name), path.join(target, name))
      }
    }
    args.push('--output', outputRoot, '--app-root', appRoot, '--assets', cacheAssets)
    if (process.env.STELLA_OFFLINE === '1') args.push('--offline')
    this.child = spawn(executable, args, { cwd: projectRoot, windowsHide: true, stdio: 'pipe', env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' } })
    const lines = createInterface({ input: this.child.stdout })
    lines.on('line', line => {
      try {
        const value = JSON.parse(line)
        if (typeof value.id === 'number') {
          const pending = this.pending.get(value.id)
          if (!pending) return
          this.pending.delete(value.id); clearTimeout(pending.timer)
          if (value.error) pending.reject(new Error(value.error.message))
          else pending.resolve(value.result)
        } else if (value.type === 'event') {
          this.emit('event', value)
          if (window && !window.isDestroyed()) window.webContents.send('stella:event', value)
        }
      } catch { this.emit('failure', new Error('后台返回了无效消息')) }
    })
    this.child.stderr.on('data', data => {
      const text = String(data).replace(/https?:\/\/\S+/g, '[服务地址]').slice(0, 2000)
      fs.appendFileSync(path.join(profileRoot, 'engine.log'), text)
    })
    const failed = (error: Error) => {
      for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(error) }
      this.pending.clear()
      if (!quitting && window && !window.isDestroyed()) window.webContents.send('stella:event', { type: 'event', name: 'engineError', payload: { message: error.message } })
    }
    this.child.on('error', failed)
    this.child.on('exit', code => { this.child = null; if (!quitting) failed(new Error(`后台已退出（${code}），请重新连接`)) })
  }
  request(method: string, params: Record<string, unknown> = {}): Promise<any> {
    return new Promise((resolve, reject) => {
      if (!this.child || this.child.killed) return reject(new Error('后台未连接，请重新连接'))
      const id = ++this.counter
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('后台响应超时，请检查任务面板')) }, 60000)
      this.pending.set(id, { resolve, reject, timer })
      this.child.stdin.write(JSON.stringify({ id, method, params })+'\n', error => {
        if (error) { clearTimeout(timer); this.pending.delete(id); reject(error) }
      })
    })
  }
}
const engine = new EngineClient()
engine.on('failure', error => console.error(error.message))

function grant(file: string, kind: 'import' | 'export') {
  const token = randomUUID(); tokens.set(token, { path: path.resolve(file), kind }); return token
}
function redeem(token: unknown, kind: 'import' | 'export') {
  if (typeof token !== 'string' || tokens.get(token)?.kind !== kind) throw new Error('文件选择已失效，请重新选择')
  const value = tokens.get(token)!.path
  return value
}
function trustedSender(event: Electron.IpcMainInvokeEvent) {
  if (!window || event.sender !== window.webContents || !event.senderFrame) throw new Error('不受信任的调用')
  const address = event.senderFrame.url
  const devUrl = !app.isPackaged ? process.env.VITE_DEV_SERVER_URL : undefined
  if (!address.startsWith('app://ui/') && !(devUrl && new URL(address).origin === new URL(devUrl).origin)) throw new Error('不受信任的页面')
}

ipcMain.handle('stella:request', async (event, method, raw) => {
  trustedSender(event)
  if (typeof method !== 'string' || (!methods.has(method) && !['files.selectImport','files.selectExport','shell.openExports','shell.copyArchive','shell.copyBind','shell.manualUpload','engine.reconnect','app.loaded'].includes(method))) throw new Error('不支持的操作')
  if (raw !== undefined && (raw === null || Array.isArray(raw) || typeof raw !== 'object')) throw new Error('参数无效')
  const params: Record<string, any> = raw ? { ...(raw as Record<string, any>) } : {}
  if (method === 'app.loaded') {
    uiReady = true
    window?.show()
    if (process.env.STELLA_READY_FILE) fs.writeFileSync(process.env.STELLA_READY_FILE, JSON.stringify({ pid: process.pid, output: outputRoot, profile: profileRoot, packaged: app.isPackaged }))
    return { ok: true }
  }
  if (method === 'files.selectImport') {
    const result = await dialog.showOpenDialog(window!, { properties: ['openFile', 'multiSelections'], filters: [{ name: '抽卡记录', extensions: ['json', 'csv'] }] })
    return result.filePaths.map(file => ({ token: grant(file, 'import'), name: path.basename(file) }))
  }
  if (method === 'files.selectExport') {
    const result = await dialog.showOpenDialog(window!, { properties: ['openDirectory', 'createDirectory'] })
    return result.filePaths[0] ? { token: grant(result.filePaths[0], 'export') } : null
  }
  if (method === 'records.import') {
    if (!Array.isArray(params.tokens) || params.tokens.length > 100) throw new Error('请选择有效文件')
    params.paths = params.tokens.map((token: unknown) => redeem(token, 'import'))
    delete params.tokens
  }
  if (method === 'records.export') { params.directory = redeem(params.token, 'export'); delete params.token }
  if (method.startsWith('shell.')) {
    if (method === 'shell.openExports') {
      const error = await shell.openPath(outputRoot); if (error) throw new Error('无法打开数据目录'); return { ok: true }
    }
    if (method === 'shell.manualUpload') {
      const address = 'https://share.fnnas.net/s/8b355174d383436899'
      clipboard.writeText(address); await shell.openExternal(address); return { ok: true }
    }
    const state = await engine.request('app.state')
    const text = method === 'shell.copyArchive' ? state.archivePath : state.bindCommand
    if (!text) throw new Error('尚无可复制的内容')
    clipboard.writeText(text); return { ok: true }
  }
  if (method === 'engine.reconnect') {
    if (!engine.child) engine.start()
    return engine.request('app.state')
  }
  if (method === 'updates.install') {
    params.waitPids = [...new Set([process.pid, ...app.getAppMetrics().map(metric => metric.pid)])]
    const result = await engine.request(method, params)
    quitting = true
    await engine.request('app.shutdown')
    app.quit()
    return result
  }
  if (method === 'app.state') {
    initialState = await engine.request(method, params)
    nativeTheme.themeSource = initialState.preferences.color_mode === 'dark' ? 'dark' : 'light'
    window?.setBackgroundColor(nativeTheme.themeSource === 'dark' ? '#10151c' : '#f2f7fb')
    return initialState
  }
  const result = await engine.request(method, params)
  if (method === 'preferences.save' && params.color_mode) nativeTheme.themeSource = params.color_mode === 'dark' ? 'dark' : 'light'
  return result
})

async function serveFile(target: string) {
  try {
    return await net.fetch(pathToFileURL(target).toString())
  } catch {
    try {
      const data = fs.readFileSync(target)
      const types: Record<string, string> = {
        '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml',
        '.ico': 'image/x-icon', '.json': 'application/json; charset=utf-8',
        '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf',
      }
      return new Response(data, { headers: { 'content-type': types[path.extname(target).toLowerCase()] || 'application/octet-stream' } })
    } catch {
      return new Response('Not found', { status: 404 })
    }
  }
}

async function createWindow() {
  protocol.handle('app', request => {
    const address = new URL(request.url)
    const relative = decodeURIComponent(address.pathname).replace(/^\/+/, '')
    let root: string
    let target: string
    if (address.hostname === 'assets') {
      if (!/^(?:(?:travelers|discs)\/\d+\.png|app_icon\.(png|ico))$/.test(relative)) return new Response('Not found', { status: 404 })
      root = assetsRoot; target = path.join(cacheAssets, relative)
      if (!fs.existsSync(target)) target = path.join(root, relative)
    } else if (address.hostname === 'ui') {
      root = path.join(frontendRoot, 'dist')
      target = path.resolve(root, relative || 'index.html')
      if (!target.startsWith(root+path.sep)) return new Response('Forbidden', { status: 403 })
    } else return new Response('Not found', { status: 404 })
    return serveFile(target)
  })
  engine.start()
  window = new BrowserWindow({ width: 1360, height: 900, minWidth: 960, minHeight: 680, show: false,
    title: '星塔旅人 · 招募档案'+(app.isPackaged ? '' : ' · Electron 预览'), icon: path.join(assetsRoot, 'app_icon.ico'), backgroundColor: '#f3f7fa',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true } })
  window.setMenuBarVisibility(false)
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
  window.webContents.on('will-navigate', (event, address) => {
    const devUrl = !app.isPackaged ? process.env.VITE_DEV_SERVER_URL : undefined
    if (!address.startsWith('app://ui/') && !(devUrl && address.startsWith(devUrl))) event.preventDefault()
  })
  window.webContents.on('page-title-updated', event => { event.preventDefault(); window?.setTitle('星塔旅人 · 招募档案'+(app.isPackaged ? '' : ' · Electron 预览')) })
  window.once('ready-to-show', () => { if (uiReady) window?.show(); else setTimeout(() => window?.show(), 8000) })
  window.on('close', event => {
    if (quitting) return
    event.preventDefault()
    void (async () => {
      try {
        const state = await engine.request('app.lifecycle')
        if (state.busy) {
          await dialog.showMessageBox(window!, { type: 'info', message: '正在完成当前操作，请稍后关闭。' }); return
        }
        if (['downloading', 'verifying'].includes(state.update?.status)) {
          const result = await dialog.showMessageBox(window!, { type: 'question', buttons: ['继续下载', '停止并退出'], defaultId: 0, cancelId: 0, message: '退出将停止未完成的更新下载。' })
          if (result.response === 0) return
        }
        await engine.request('app.shutdown')
      } catch {
        if (engine.child) {
          await dialog.showMessageBox(window!, { type: 'info', message: '后台正在结束当前操作，请稍后再关闭。' })
          return
        }
      }
      quitting = true; app.quit()
    })()
  })
  const devUrl = !app.isPackaged ? process.env.VITE_DEV_SERVER_URL : undefined
  await window.loadURL(devUrl || 'app://ui/index.html')
}

const instance = app.requestSingleInstanceLock({ output: outputRoot })
if (!instance) app.quit()
else {
  app.on('second-instance', () => { window?.show(); window?.focus() })
  app.whenReady().then(createWindow).catch(error => {
    console.error(error); dialog.showErrorBox('启动失败', String(error)); app.quit()
  })
}
app.on('before-quit', () => { quitting = true; engine.child?.stdin.end() })
app.on('window-all-closed', () => app.quit())
