import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import { useAppStore } from '../../src/store'
import type { AppState } from '../../src/types'
import UploadView from '../../src/views/UploadView.vue'

let request: ReturnType<typeof vi.fn>
let wrappers: ReturnType<typeof mount>[]

function state(): AppState {
  return {
    protocolVersion: 1, version: '1.3.0.beta.5', busy: false, offline: false, packaged: false,
    preferences: { color_mode: 'light', auto_upload: false, auto_upload_hhmx: false, auto_update: true, pool_columns: null, update_channel: 'beta' },
    accounts: [{ key: 'default', uid: '100000001', name: '', label: '默认账号', groups: 1 }],
    activeAccount: 'default', server: 'cn', serverManual: false, servers: [{ key: 'cn', label: '国服' }],
    archivePath: 'D:/exports/100000001.json', outputPath: 'D:/exports', bindCommand: '星塔抽卡绑定 UID 100000001',
    tasks: [], update: { status: 'idle' },
    summary: { uid: '100000001', pulls: 10, five: 1, rate: 10, average: 10, groups: 1, categories: [], activity: [], firstTime: 0, lastTime: 0 },
  }
}

function mountPage() {
  const wrapper = mount(UploadView, { attachTo: document.body, global: { plugins: [Antd] } })
  wrappers.push(wrapper)
  return wrapper
}

function buttonByText(view: ReturnType<typeof mountPage>, text: string) {
  const button = view.findAll('button').find(item => item.text().replace(/\s/g, '') === text)
  expect(button).toBeTruthy()
  return button!
}

beforeEach(() => {
  setActivePinia(createPinia())
  wrappers = []
  request = vi.fn().mockImplementation(async (method: string, params: Record<string, unknown> = {}) => {
    if (method === 'preferences.save') return { ...useAppStore().state!.preferences, ...params }
    return { ok: true }
  })
  window.stella = { request, onEvent: () => () => {} }
  useAppStore().state = state()
})

afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount()
  document.body.innerHTML = ''
})

describe('automatic upload to hhmx.cn', () => {
  it('uses its own preference and leaves the Rem switch untouched', async () => {
    const view = mountPage()
    expect(view.text()).toContain('自动上传到 hhmx.cn')
    expect(view.text()).toContain('目标站点')
    expect(view.text()).toContain('已关闭')
    expect(view.text()).toContain('上传到蕾姆')

    await view.get('.auto-upload-toggle .ant-switch').trigger('click')
    await flushPromises()

    expect(request).toHaveBeenCalledWith('preferences.save', { auto_upload_hhmx: true })
    expect(useAppStore().state!.preferences.auto_upload_hhmx).toBe(true)
    expect(useAppStore().state!.preferences.auto_upload).toBe(false)
    expect(view.text()).toContain('已开启')
    expect(view.text()).toContain('这不会改变蕾姆自动上传')
  })

  it('keeps the hhmx preference editable offline and explains when it takes effect', async () => {
    const offline = state()
    offline.offline = true
    offline.preferences.auto_upload_hhmx = true
    useAppStore().state = offline

    const view = mountPage()
    expect(view.text()).toContain('当前离线')
    expect(view.text()).toContain('已开启')
    const toggle = view.get('.auto-upload-toggle .ant-switch')
    expect(toggle.attributes('disabled')).toBeUndefined()
    await toggle.trigger('click')
    await flushPromises()
    expect(request).toHaveBeenCalledWith('preferences.save', { auto_upload_hhmx: false })
    expect(useAppStore().state!.preferences.auto_upload_hhmx).toBe(false)
    expect(view.text()).toContain('离线模式下不会上传')
    expect(view.get('.upload-summary .ant-btn').attributes('disabled')).toBeDefined()
    expect(buttonByText(view, '上传到hhmx.cn').attributes('disabled')).toBeDefined()
  })

  it('keeps both manual upload destinations available', async () => {
    const view = mountPage()
    await view.get('.upload-summary .ant-btn').trigger('click')
    await buttonByText(view, '上传到hhmx.cn').trigger('click')
    await flushPromises()

    expect(request).toHaveBeenCalledWith('upload.send', {})
    expect(request).toHaveBeenCalledWith('upload.sendHhmx', {})
    expect(view.text()).toContain('打开蕾姆手动上传页')
    expect(view.text()).toContain('hhmx.cn 不需要这条指令')
  })
})
