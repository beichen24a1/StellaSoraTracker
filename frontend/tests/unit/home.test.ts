import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import Antd from 'ant-design-vue'
import HomeView from '../../src/views/HomeView.vue'
import { useAppStore } from '../../src/store'
import type { AppState, HomeSummary } from '../../src/types'

let wrapper: ReturnType<typeof mount> | undefined
let request: ReturnType<typeof vi.fn>
const empty = { available: false, count: 0, highestLevel: 0, updatedAt: '', portraits: [], emblems: 0 }
function snapshot(): HomeSummary {
  const owner = useAppStore().state!.activeAccount
  return { accountKey: owner, uid: owner === 'A' ? '100000001' : '100000002',
    roster: { ...empty, available: true, count: 12, highestLevel: 90, portraits: [{ id: 130, name: owner+'的多娜', level: 90 }] },
    affinity: { ...empty, available: true, count: 10, highestLevel: 65 }, recentFive: [] }
}
const calendar = { items: [], updatedAt: 0, loading: false, stale: false, offline: true, error: '', source: '', sourceUrl: '' }
beforeEach(() => {
  setActivePinia(createPinia())
  useAppStore().state = { activeAccount: 'A', accounts: [{ key: 'A', uid: '100000001', name: '账号 A' }, { key: 'B', uid: '100000002', name: '账号 B' }],
    summary: { pulls: 1200, five: 28, lastTime: 0 }, servers: [], tasks: [], preferences: { color_mode: 'light' } } as unknown as AppState
  request = vi.fn(async (method: string) => method === 'home.summary' ? snapshot() : calendar)
  window.stella = { request, onEvent: () => () => {} }
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; useAppStore().$dispose(); document.body.innerHTML = '' })
async function page() {
  const router = createRouter({ history: createMemoryHistory(), routes: ['/', '/overview', '/records', '/roster', '/affinity', '/calendar', '/settings', '/upload', '/help'].map(path => ({ path, component: { template: '<div/>' } })) })
  await router.push('/')
  wrapper = mount(HomeView, { global: { plugins: [router, Antd] } })
  await flushPromises()
  return router
}
it('shows real account summaries and navigates to the existing features', async () => {
  const router = await page()
  expect(wrapper!.text()).toContain('1,200')
  expect(wrapper!.text()).toContain('A的多娜')
  expect(wrapper!.text()).toContain('65')
  await wrapper!.get('a[href="/roster"]').trigger('click')
  await flushPromises()
  expect(router.currentRoute.value.path).toBe('/roster')
  expect(request.mock.calls.every(([method]) => ['home.summary', 'calendar.get'].includes(method))).toBe(true)
})
it('clears old data and ignores a late response when the account changes', async () => {
  let resolveA!: (value: unknown) => void
  const previous = snapshot()
  request.mockImplementation(async (method: string) => method !== 'home.summary' ? calendar
    : useAppStore().state!.activeAccount === 'A' ? new Promise(resolve => { resolveA = resolve }) : snapshot())
  await page()
  useAppStore().state!.activeAccount = 'B'
  await flushPromises()
  resolveA(previous)
  await flushPromises()
  expect(wrapper!.text()).toContain('B的多娜')
  expect(wrapper!.text()).not.toContain('A的多娜')
})
it('shows honest empty states and only reads the game after an explicit action', async () => {
  request.mockImplementation(async (method: string) => method === 'home.summary' ? { ...snapshot(), roster: empty, affinity: empty } : calendar)
  await page()
  expect(wrapper!.text()).toContain('还没有角色数据')
  expect(wrapper!.text()).toContain('还没有好感度记录')
  expect(request).not.toHaveBeenCalledWith('roster.read', expect.anything())
  const button = wrapper!.findAll('button').find(value => value.text().includes('任务与日志'))!
  await button.trigger('click')
  expect(useAppStore().taskDrawer).toBe(true)
})
it('supports retry after a failed summary request', async () => {
  let failed = false
  request.mockImplementation(async (method: string) => {
    if (method !== 'home.summary') return calendar
    if (!failed) { failed = true; throw new Error('后台未连接') }
    return snapshot()
  })
  await page()
  expect(wrapper!.text()).toContain('后台未连接')
  await wrapper!.get('button[aria-label="重新加载主页摘要"]').trigger('click')
  await flushPromises()
  expect(wrapper!.text()).toContain('A的多娜')
  expect(wrapper!.text()).not.toContain('后台未连接')
})
