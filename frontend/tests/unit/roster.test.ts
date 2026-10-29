import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import { useAppStore } from '../../src/store'
import type { AppState, EngineEvent } from '../../src/types'
import RosterView from '../../src/views/RosterView.vue'
import EmblemThumbnail from '../../src/components/EmblemThumbnail.vue'

let request: ReturnType<typeof vi.fn>
let wrappers: ReturnType<typeof mount>[]
let emit: (event: EngineEvent) => void

function state(): AppState {
  return { protocolVersion:1,version:'1.3.0.bata2',busy:false,offline:false,packaged:true,
    preferences:{color_mode:'light',auto_upload:false,auto_update:true,pool_columns:null,update_channel:'beta'},
    accounts:[{key:'default',uid:'100000001',name:'',label:'默认账号',groups:0},{key:'B',uid:'100000002',name:'',label:'B',groups:0}],activeAccount:'default',server:'cn',serverManual:false,
    servers:[{key:'cn',label:'国服'}],archivePath:'D:/exports/default.json',outputPath:'D:/exports',bindCommand:'',tasks:[],update:{status:'idle'},
    summary:{uid:'',pulls:0,five:0,rate:0,average:null,groups:0,categories:[],activity:[],firstTime:0,lastTime:0} }
}

function installStella(routes: Record<string, (params: any) => unknown>) {
  request = vi.fn().mockImplementation(async (method: string, params: any) => {
    if (method in routes) return routes[method](params)
    return { ok: true }
  })
  window.stella = { request, onEvent: callback => { emit = callback; return () => {} } }
}

function character() {
  return {
    id: 130, name: '多娜', level: 90, advance: 8, favorite: true, skills: [1, 1, 10, 8, 1],
    talent: { active: 11, max: 50, nodes: [1300101], names: ['攻击强化'], descs: ['基础攻击提升…'], fate: [1300116] },
    potentials: { master_specific: ['腾蛇凌波'], common: ['蛇舞涟漪'] },
    slots: [
      { slot: 1, name: '尖章', unlockLevel: 70 },
      { slot: 2, name: '方菱章', unlockLevel: 80 },
      { slot: 3, name: '星闪章', unlockLevel: 90 },
    ],
    emblems: [{
      slot: 1, slotName: '尖章', index: 1, preset: 1, active: true, name: '虔信者尖章', type: 3, typeName: '尖章',
      gemId: 101, generateId: 35001, refreshId: 35001, icon: '', desc: '闪烁着虔诚力量的尖章。',
      locked: false, upgrades: [0, 0, 1, 0], alterUpgrades: [0, 0, 0, 0], affixes: [804, 2603],
      alterAffixes: [], skillAffixes: [{ typeId: 37, id: 3702, level: 2, name: '援护技能等级提升 +2级' }],
      potentialAffixes: [], affixNames: ['暴击伤害', '攻击'],
      attrs: [{ attrId: 804, value: 0.15, cfgValue: 1500, name: '暴击伤害' }],
    }],
  }
}

beforeEach(() => {
  setActivePinia(createPinia()); wrappers = []
  useAppStore().state = state()
})
afterEach(() => {
  useAppStore().dispose()
  useAppStore().$dispose()
  for (const wrapper of wrappers) wrapper.unmount()
  document.body.innerHTML = ''
})

function mountPage() {
  const wrapper = mount(RosterView, { attachTo: document.body, global: { plugins: [Antd] } })
  wrappers.push(wrapper)
  return wrapper
}

describe('roster page', () => {
  it('reloads the account cache after switching accounts outside the roster route', async () => {
    installStella({ 'roster.load': () => {
      const other = useAppStore().state!.activeAccount === 'B'
      return { uid: other ? '100000002' : '100000001', characters: [{ ...character(), name: other ? 'B 的旅人' : 'A 的旅人' }] }
    } })
    const first = mountPage()
    await flushPromises()
    expect(first.text()).toContain('A 的旅人')
    first.unmount()
    useAppStore().state!.activeAccount = 'B'
    await flushPromises()
    const returned = mountPage()
    await flushPromises()
    expect(returned.text()).toContain('B 的旅人')
    expect(returned.text()).not.toContain('A 的旅人')
  })

  it('discards a cache response arriving after the account has changed', async () => {
    let resolveA!: (value: unknown) => void
    installStella({ 'roster.load': () => useAppStore().state!.activeAccount === 'B'
      ? { uid: '100000002', characters: [{ ...character(), name: 'B 的旅人' }] }
      : new Promise(resolve => { resolveA = resolve }) })
    const view = mountPage()
    useAppStore().state!.activeAccount = 'B'
    await flushPromises()
    resolveA({ uid: '100000001', characters: [{ ...character(), name: 'A 的旅人' }] })
    await flushPromises()
    expect(view.text()).toContain('B 的旅人')
    expect(view.text()).not.toContain('A 的旅人')
  })

  it('ignores a live read completed for the previous account', async () => {
    const store = useAppStore()
    store.state!.offline = true
    installStella({ 'app.state': () => store.state, 'app.loaded': () => ({}),
      'roster.load': () => ({ uid: store.state!.activeAccount === 'B' ? '100000002' : '100000001', characters: [] }),
      'processes.list': () => [{ name: 'xtlr.exe', pid: 9, path: '' }], 'roster.read': () => ({ operationId: 'old-read' }) })
    await store.initialize()
    const view = mountPage()
    await flushPromises()
    await store.capture('roster.read')
    store.state!.activeAccount = 'B'
    await flushPromises()
    emit({ type: 'event', name: 'result', payload: { operationId: 'old-read', result: { uid: '100000001', characters: [character()] } } })
    await flushPromises()
    expect(store.rosterUid).toBe('100000002')
    expect(view.findAll('.roster-card')).toHaveLength(0)
  })

  it('accepts a current-account read even if its event precedes the request response', async () => {
    const store = useAppStore()
    store.state!.offline = true
    installStella({ 'app.state': () => store.state, 'app.loaded': () => ({}),
      'roster.load': () => ({ uid: '100000001', characters: [] }),
      'processes.list': () => [{ name: 'xtlr.exe', pid: 9, path: '' }],
      'roster.read': () => {
        emit({ type: 'event', name: 'result', payload: { operationId: 'fast-read', result: { uid: '100000001', characters: [character()] } } })
        return { operationId: 'fast-read' }
      } })
    await store.initialize()
    const view = mountPage()
    await flushPromises()
    await store.capture('roster.read')
    await flushPromises()
    expect(view.text()).toContain('多娜')
    expect(store.rosterBusy).toBe(false)
  })

  it('retries a failed cache load on the next visit', async () => {
    let attempts = 0
    installStella({ 'roster.load': () => {
      if (++attempts === 1) throw new Error('backend disconnected')
      return { uid: '100000001', characters: [character()] }
    } })
    const first = mountPage()
    await flushPromises()
    first.unmount()
    const returned = mountPage()
    await flushPromises()
    expect(returned.text()).toContain('多娜')
    expect(attempts).toBe(2)
  })

  it('puts starred characters first', async () => {
    const other = { ...character(), id: 131, name: '星见', favorite: false, level: 95 }
    installStella({
      'roster.load': () => ({ uid: '100000001', updatedAt: '2026-10-27T12:00:00+08:00',
        characters: [other, character()] }),
    })
    const wrapper = mountPage()
    await flushPromises()
    const names = wrapper.findAll('.roster-card .title strong').map(node => node.text())
    expect(names[0]).toBe('多娜')
  })

  it('shows level, skills, talent and emblems from the saved result', async () => {
    const hero = character()
    hero.emblems.push({ ...hero.emblems[0], index: 2, active: false, name: '虔信者尖章·备用' })
    installStella({
      'roster.load': () => ({ uid: '100000001', updatedAt: '2026-10-27T12:00:00+08:00',
        characters: [hero] }),
    })
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('100000001')
    expect(text).toContain('多娜')
    expect(text).toContain('Lv.90')
    expect(text).toContain('突破 8')
    expect(text).toContain('技能3')
    expect(text).toContain('11 / 50')
    expect(text).toContain('虔信者尖章')
    expect(wrapper.findAll('.roster-card')).toHaveLength(1)

    await wrapper.find('.card-head').trigger('click')
    await flushPromises()
    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('暴击伤害')
    expect(bodyText).toContain('攻击强化')
    expect(bodyText).toContain('援护技能等级提升 +2级')
    expect(bodyText).toContain('腾蛇凌波')
    expect(bodyText).toContain('蛇舞涟漪')
    expect(document.querySelectorAll('.detail-modal .emblem')).toHaveLength(2)
    expect(document.querySelectorAll('.detail-modal .emblem.equipped')).toHaveLength(1)
    expect(bodyText).toContain('装备中')
    expect(bodyText).toContain('虔信者尖章·备用')
    expect(bodyText).not.toContain('闪烁着虔诚力量')
    expect(document.querySelector('.emblem-thumbnail img')?.getAttribute('src')).toBe('app://assets/emblems/101.png')
  })

  it('reads from the game when the refresh button is pressed', async () => {
    installStella({
      'roster.load': () => ({ updatedAt: '', characters: [] }),
      'processes.list': () => [{ name: 'xtlr.exe', pid: 9, path: '' }],
      'roster.read': () => ({ operationId: 'op-9' }),
    })
    const wrapper = mountPage()
    await flushPromises()

    const button = wrapper.findAll('button').find(value => value.text().includes('读取角色数据'))
    expect(button).toBeTruthy()
    await button!.trigger('click')
    await flushPromises()

    expect(request).toHaveBeenCalledWith('roster.read', { pid: 9 })
    expect(useAppStore().rosterBusy).toBe(true)
  })

  it('opens a separate emblem dialog from a slot', async () => {
    installStella({
      'roster.load': () => ({ uid: '100000001', updatedAt: '2026-10-27T12:00:00+08:00',
        characters: [character()] }),
    })
    const wrapper = mountPage()
    await flushPromises()

    const slot = wrapper.find('.slot.clickable')
    expect(slot.exists()).toBe(true)
    await slot.trigger('click')
    await flushPromises()
    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('虔信者尖章')
    expect(bodyText).toContain('暴击伤害')
    expect(bodyText).not.toContain('闪烁着虔诚力量')
  })

  it('matches emblem artwork by the game icon, and handles unknown or missing images locally', async () => {
    const view = mount(EmblemThumbnail, { props: { emblem: { name: '保卫者尖章', icon: 'Equipment/103/103' } } })
    wrappers.push(view)
    expect(view.get('img').attributes('src')).toBe('app://assets/emblems/301.png')
    await view.get('img').trigger('error')
    expect(view.find('img').exists()).toBe(false)
    await view.setProps({ emblem: { name: '虔信者方菱章', icon: '' } })
    expect(view.get('img').attributes('src')).toBe('app://assets/emblems/102.png')
    await view.setProps({ emblem: { name: '未收录纹章', icon: 'https://example.com/private.png' } })
    expect(view.find('img').exists()).toBe(false)
    expect(view.find('.emblem-placeholder').exists()).toBe(true)
  })

  it('renders an empty state before the first read', async () => {
    installStella({ 'roster.load': () => ({ updatedAt: '', characters: [] }) })
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('还没有角色数据')
    expect(wrapper.findAll('.roster-card')).toHaveLength(0)
  })
})
