import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import { useAppStore } from '../../src/store'
import type { AppState } from '../../src/types'
import AffinityView from '../../src/views/AffinityView.vue'

let request: ReturnType<typeof vi.fn>
let wrappers: ReturnType<typeof mount>[]

function state(): AppState {
  return { protocolVersion:1,version:'1.3.0.bata2',busy:false,offline:false,packaged:true,
    preferences:{color_mode:'light',auto_upload:false,auto_update:true,pool_columns:null,update_channel:'beta'},
    accounts:[{key:'default',uid:'',name:'',label:'默认账号',groups:0}],activeAccount:'default',server:'cn',serverManual:false,
    servers:[{key:'cn',label:'国服'}],archivePath:'D:/exports/default.json',outputPath:'D:/exports',bindCommand:'',tasks:[],update:{status:'idle'},
    summary:{uid:'',pulls:0,five:0,rate:0,average:null,groups:0,categories:[],activity:[],firstTime:0,lastTime:0} }
}

function installStella(routes: Record<string, (params: any) => unknown>) {
  request = vi.fn().mockImplementation(async (method: string, params: any) => {
    if (method in routes) return routes[method](params)
    return { ok: true }
  })
  window.stella = { request, onEvent: () => () => {}, importFiles: vi.fn() }
}

beforeEach(() => {
  setActivePinia(createPinia()); wrappers = []
  useAppStore().state = state()
})
afterEach(() => {
  for (const wrapper of wrappers) wrapper.unmount()
  document.body.innerHTML = ''
})

function mountPage() {
  const wrapper = mount(AffinityView, { attachTo: document.body, global: { plugins: [Antd] } })
  wrappers.push(wrapper)
  return wrapper
}

describe('affinity page', () => {
  it('shows the saved result with level, exp and next-level requirement', async () => {
    installStella({
      'affinity.load': () => ({ uid: '100000001', updatedAt: '2026-10-27T12:00:00+08:00', entries: [
        { id: 156, name: '小禾', level: 65, exp: 6040, need: 33100, ratio: 0.1825, favorite: true },
        { id: 130, name: '多娜', level: 12, exp: 1575, need: 2000, ratio: 0.7875, favorite: false },
      ] }),
    })
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('100000001')
    expect(text).toContain('小禾')
    expect(text).toContain('Lv.65')
    expect(text).toContain('6,040 / 33,100')
    expect(text).toContain('多娜')
    expect(wrapper.findAll('.affinity-card')).toHaveLength(2)
    expect(text).toContain('2026/10/27')
  })

  it('reads from the game when the refresh button is pressed', async () => {
    installStella({
      'affinity.load': () => ({ updatedAt: '', entries: [] }),
      'processes.list': () => [{ name: 'xtlr.exe', pid: 9, path: '' }],
      'affinity.read': () => ({ operationId: 'op-9' }),
    })
    const wrapper = mountPage()
    await flushPromises()

    const button = wrapper.findAll('button').find(value => value.text().includes('读取好感度'))
    expect(button).toBeTruthy()
    await button!.trigger('click')
    await flushPromises()

    expect(request).toHaveBeenCalledWith('affinity.read', { pid: 9 })
    expect(useAppStore().affinityBusy).toBe(true)
  })

  it('renders an empty state before the first read', async () => {
    installStella({ 'affinity.load': () => ({ updatedAt: '', entries: [] }) })
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('还没有好感度数据')
    expect(wrapper.findAll('.affinity-card')).toHaveLength(0)
  })
})
