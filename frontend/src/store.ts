import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { message } from './feedback'
import type { AppState, Task, UpdateState, Preferences, EngineEvent, ImportFile, AffinityEntry, RosterCharacter, ClosePrompt } from './types'

export const useAppStore = defineStore('app', () => {
  const state = ref<AppState | null>(null)
  const error = ref('')
  const loading = ref(false)
  const tasks = ref<Task[]>([])
  const taskDrawer = ref(false)
  const closePrompt = ref<ClosePrompt | null>(null)
  const updateOpen = ref(false)
  const update = ref<UpdateState>({ status: 'idle' })
  const processes = ref<{ name: string; pid: number; path: string }[]>([])
  const processDialog = ref(false)
  const selectedPid = ref<number | null>(null)
  const processAction = ref<'records.capture' | 'uid.read' | 'affinity.read' | 'roster.read'>('records.capture')
  const lastOperation = ref('已准备就绪')
  const affinity = ref<AffinityEntry[]>([])
  const affinityUpdated = ref('')
  const affinityUid = ref('')
  const affinityPath = ref('')
  const affinityBusy = ref(false)
  const affinityLoaded = ref(false)
  const roster = ref<RosterCharacter[]>([])
  const rosterUpdated = ref('')
  const rosterUid = ref('')
  const rosterPath = ref('')
  const rosterBusy = ref(false)
  const rosterOwner = computed(() => state.value?.accounts.find(account => account.key === state.value?.activeAccount)?.uid || '')
  const rosterContext = computed(() => JSON.stringify([state.value?.activeAccount || '', rosterOwner.value]))
  let rosterVisited = false
  let rosterLoadedFor: string | null = null
  let rosterEpoch = 0
  let rosterLoadSerial = 0
  let rosterCapture: { context: string; epoch: number } | null = null
  const recordsFilter = ref({ category: 'all', query: '', mode: 'five', page: 1, pageSize: 10, ascending: false, fiveOnly: false, gid: null as number | null })
  const busy = computed(() => state.value?.busy || tasks.value.some(task => task.exclusive && task.state === 'running'))
  const activeTask = computed(() => tasks.value.find(task => task.state === 'running'))
  const colorMode = computed(() => state.value?.preferences.color_mode || 'light')
  let unsub: (() => void) | undefined
  let refreshTimer: ReturnType<typeof setTimeout> | undefined

  async function refresh() {
    try {
      const value = await window.stella.request<AppState>('app.state')
      if (value.protocolVersion !== 1) throw new Error('界面与后台版本不兼容，请完整解压程序后重试')
      state.value = value
      tasks.value = value.tasks
      update.value = value.update
      error.value = ''
      document.documentElement.dataset.theme = value.preferences.color_mode
    } catch (reason) { error.value = String(reason).replace(/^Error: /, '') }
  }
  function scheduleRefresh() {
    clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => void refresh(), 80)
  }
  function event(value: EngineEvent) {
    if (value.name === 'closePrompt') closePrompt.value = value.payload
    if (value.name === 'task') {
      const task = value.payload as Task
      const index = tasks.value.findIndex(item => item.id === task.id)
      if (index < 0) tasks.value.unshift(task)
      else tasks.value[index] = task
      tasks.value = tasks.value.slice(0, 100)
      lastOperation.value = task.logs.at(-1)?.message || task.label
      if (task.state === 'failed' && !['检查更新', '下载更新'].includes(task.label)) { message.error(task.error || `${task.label}未完成`); taskDrawer.value = true }
      if (task.state !== 'running') scheduleRefresh()
    }
    if (value.name === 'changed') { if (state.value) state.value.busy = value.payload.busy; scheduleRefresh() }
    if (value.name === 'engineError') { error.value = value.payload.message; rosterBusy.value = false; rosterCapture = null }
    if (value.name === 'update') {
      const previous = update.value.status
      update.value = value.payload
      if (value.payload.status === 'idle') updateOpen.value = false
      if (['available', 'ready', 'failed'].includes(value.payload.status) && previous !== value.payload.status) updateOpen.value = true
    }
    if (value.name === 'result' && value.payload.result?.bindCommand) {
      if (state.value) state.value.bindCommand = value.payload.result.bindCommand
    }
    if (value.name === 'task' && value.payload.label === '读取好感度') {
      affinityBusy.value = value.payload.state === 'running'
    }
    if (value.name === 'result' && value.payload.result?.entries) {
      affinity.value = value.payload.result.entries
      affinityUpdated.value = value.payload.result.updatedAt || ''
      affinityUid.value = value.payload.result.uid || ''
      affinityPath.value = value.payload.result.path || affinityPath.value
      affinityBusy.value = false
    }
    if (value.name === 'task' && value.payload.label === '读取角色数据') {
      rosterBusy.value = value.payload.state === 'running'
      if (value.payload.state === 'failed' || value.payload.state === 'cancelled') rosterCapture = null
    }
    if (value.name === 'result' && Array.isArray(value.payload.result?.characters)) {
      const result = value.payload.result
      if (rosterCapture?.context === rosterContext.value && rosterCapture.epoch === rosterEpoch) {
        if (!rosterOwner.value || result.uid === rosterOwner.value) {
          ++rosterLoadSerial // A pending cache load must not replace this newer read.
          roster.value = result.characters
          rosterUpdated.value = result.updatedAt || ''
          rosterUid.value = result.uid || ''
          rosterPath.value = result.path || ''
          rosterLoadedFor = rosterContext.value
        } else {
          message.warning('角色数据已保存至对应 UID，请切换到该账号查看')
        }
      }
      rosterCapture = null
      rosterBusy.value = false
    }
    if (value.name === 'result' && value.payload.result?.warnings?.length) message.warning('记录已保存，部分附加操作未完成，详见任务日志')
    if (value.name === 'result' && value.payload.result?.failures?.length) message.warning('部分文件导入失败，详见任务日志')
  }
  async function initialize() {
    loading.value = true
    unsub?.(); unsub = window.stella.onEvent(event)
    await refresh()
    loading.value = false
    await window.stella.request('app.loaded')
    if (state.value?.update.status === 'ready') updateOpen.value = true
    if (state.value?.packaged && !state.value.offline && state.value.preferences.auto_update) setTimeout(() => void invoke('updates.check', { automatic: true }, false), 1500)
    if (state.value && !state.value.offline && !busy.value) void invoke('resources.sync', { background: true }, false)
  }
  async function invoke<T=any>(method: string, params: Record<string, unknown> = {}, notify = true): Promise<T | undefined> {
    try {
      const result = await window.stella.request<T>(method, params)
      if ((result as any)?.operationId) { lastOperation.value = '操作已开始'; scheduleRefresh() }
      return result
    } catch (reason) {
      const text = String(reason).replace(/^Error: /, '')
      lastOperation.value = text
      if (notify) message.error(text)
      return undefined
    }
  }
  async function savePreferences(changes: Partial<Preferences>) {
    const result = await invoke<Preferences>('preferences.save', changes)
    if (result && state.value) { state.value.preferences = result; document.documentElement.dataset.theme = result.color_mode }
  }
  async function capture(action: 'records.capture' | 'uid.read' | 'affinity.read' | 'roster.read' = 'records.capture') {
    if (busy.value) return
    const result = await invoke<typeof processes.value>('processes.list')
    if (!result) return
    if (!result.length) { message.info('未找到游戏客户端，请先登录游戏并进入主界面'); return }
    processAction.value = action
    processes.value = result
    selectedPid.value = result[0].pid
    if (result.length === 1) await startProcess()
    else processDialog.value = true
  }
  async function startProcess() {
    processDialog.value = false
    const action = processAction.value
    if (action === 'roster.read' && rosterBusy.value) return
    if (action === 'affinity.read') affinityBusy.value = true
    if (action === 'roster.read') {
      rosterBusy.value = true
      rosterCapture = { context: rosterContext.value, epoch: rosterEpoch }
    }
    const result = await invoke(action, { pid: selectedPid.value })
    if (action === 'affinity.read' && result === undefined) affinityBusy.value = false
    if (action === 'roster.read' && result === undefined) { rosterBusy.value = false; rosterCapture = null }
  }
  async function loadAffinity(force = false) {
    if (affinityLoaded.value && !force) return
    const value = await invoke<{ entries: AffinityEntry[]; updatedAt: string; uid?: string; path?: string }>('affinity.load', {}, false)
    if (value) {
      affinity.value = value.entries || []
      affinityUpdated.value = value.updatedAt || ''
      affinityUid.value = value.uid || ''
      affinityPath.value = value.path || ''
    }
    affinityLoaded.value = true
  }
  async function loadRoster(force = false) {
    rosterVisited = true
    const context = rosterContext.value
    if (rosterLoadedFor === context && !force) return
    const serial = ++rosterLoadSerial
    const value = await invoke<{ characters: RosterCharacter[]; updatedAt: string; uid?: string; path?: string }>('roster.load', {}, false)
    if (serial !== rosterLoadSerial || context !== rosterContext.value) return
    if (value && (value.uid || '') === rosterOwner.value) {
      roster.value = value.characters || []
      rosterUpdated.value = value.updatedAt || ''
      rosterUid.value = value.uid || ''
      rosterPath.value = value.path || ''
      rosterLoadedFor = context
    }
  }
  // Store-level invalidation remains active while settings or other routes are open.
  watch(rosterContext, () => {
    ++rosterEpoch
    ++rosterLoadSerial
    rosterCapture = null
    rosterLoadedFor = null
    roster.value = []
    rosterUpdated.value = ''
    rosterUid.value = rosterOwner.value
    rosterPath.value = ''
    if (rosterVisited) void loadRoster()
  }, { flush: 'sync' })
  async function importFiles(files?: ImportFile[]) {
    if (busy.value) return
    const selected = files || await invoke<ImportFile[]>('files.selectImport')
    if (selected?.length) await invoke('records.import', { tokens: selected.map(file => file.token) })
  }
  async function exportRecords() {
    const selected = await invoke<{ token: string } | null>('files.selectExport')
    if (selected) await invoke('records.export', { token: selected.token })
  }
  function dispose() { unsub?.(); clearTimeout(refreshTimer) }
  return { state, error, loading, tasks, taskDrawer, closePrompt, update, updateOpen, processes, processDialog, selectedPid, processAction, lastOperation,
    recordsFilter, busy, activeTask, colorMode, affinity, affinityUpdated, affinityUid, affinityPath, affinityBusy,
    roster, rosterUpdated, rosterUid, rosterPath, rosterBusy,
    initialize, refresh, invoke, savePreferences, capture, startProcess, importFiles, exportRecords, loadAffinity, loadRoster, dispose }
})
