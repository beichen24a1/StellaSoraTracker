import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import CalendarView from '../../src/views/CalendarView.vue'
import { useCalendarStore } from '../../src/calendarStore'
import { calendarDate, chooseFeatured, countdown, phase } from '../../src/calendar'
import type { CalendarEntry, CalendarSnapshot, EngineEvent } from '../../src/types'

const now = Date.parse('2026-10-28T12:00:00+08:00') / 1000
const item: CalendarEntry = { id: 100, name: '星之砂', title: '「星之砂」活动说明', kind: 'event', startAt: now - 86400, endAt: now + 2 * 86400,
  startApproximate: false, description: '完成任务可领取奖励', cover: '', url: 'https://stellasora.yostar.cn/news/100' }
let snapshot: CalendarSnapshot
let request: ReturnType<typeof vi.fn>
let event: (value: EngineEvent) => void
let unsubscribe: ReturnType<typeof vi.fn>
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(Date, 'now').mockReturnValue(now * 1000)
  snapshot = { items: [item, { ...item, id: 101, name: '灾变防线', title: '灾变防线活动说明', kind: 'permanent' }], updatedAt: now,
    loading: false, stale: false, error: '', offline: false, source: '星塔旅人国服官网', sourceUrl: 'https://stellasora.yostar.cn' }
  request = vi.fn(async (method: string) => method === 'calendar.get' ? structuredClone(snapshot) : { ok: true })
  unsubscribe = vi.fn()
  window.stella = { request, onEvent: callback => { event = callback; return unsubscribe } }
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); document.body.innerHTML = '' })
async function page() { wrapper = mount(CalendarView, { global: { plugins: [Antd] } }); await flushPromises(); return wrapper }

describe('official calendar', () => {
  it('uses China time, handles exact boundaries and maintenance uncertainty', () => {
    expect(calendarDate(now)).toContain('12:00')
    expect(phase(item, item.endAt)).toBe('ended')
    expect(countdown(item, now)).toBe('2 天 0 时')
    expect(phase({ ...item, startAt: now + 60 }, now)).toBe('upcoming')
    const maintenance = { ...item, startAt: now - 100, startApproximate: true }
    expect(phase(maintenance, now)).toBe('maintenance')
    expect(countdown(maintenance, now)).toBe('以游戏维护进度为准')
    expect(chooseFeatured([item, { ...item, id: 8, kind: 'version' }], now)?.id).toBe(8)
  })
  it('selects a schedule card and opens a constrained official article', async () => {
    const view = await page()
    expect(view.text()).toContain('国服官网活动')
    expect(view.findAll('.calendar-schedule-card')).toHaveLength(2)
    await view.findAll('.calendar-schedule-card')[1]!.trigger('click')
    await flushPromises()
    expect(view.find('.calendar-hero h2').text()).toBe('灾变防线')
    await view.get('.calendar-article-link').trigger('click')
    expect(request).toHaveBeenCalledWith('shell.openCalendarArticle', { id: 101 })
    const refresh = view.findAll('button').find(button => button.text().includes('刷新活动'))!
    await refresh.trigger('click'); await flushPromises()
    expect(request).toHaveBeenCalledWith('calendar.refresh', { force: true })
  })
  it('retains filter and selection across unmount and theme navigation without a search input', async () => {
    const view = await page()
    const store = useCalendarStore()
    store.filter = 'all'
    store.selectedId = 101
    wrapper!.unmount(); wrapper = undefined
    expect(unsubscribe).toHaveBeenCalledOnce()
    const returned = await page()
    expect(store.filter).toBe('all')
    expect(returned.find('input[placeholder="搜索活动名称"]').exists()).toBe(false)
    expect(returned.find('.calendar-hero h2').text()).toBe('灾变防线')
  })
  it('keeps cached results on a failed refresh and consumes pushed progress', async () => {
    const view = await page()
    event({ type: 'event', name: 'calendar', payload: { ...snapshot, stale: true, error: '官网暂不可用，已保留上次日历。' } })
    await flushPromises()
    expect(view.text()).toContain('已保留上次日历')
    expect(view.findAll('.calendar-schedule-card')).toHaveLength(2)
  })
  it('shows honest empty and no-matching-results states', async () => {
    snapshot.items = []
    const view = await page()
    expect(view.text()).toContain('暂时没有可显示的活动')
    event({ type: 'event', name: 'calendar', payload: { ...snapshot, items: [item] } })
    useCalendarStore().filter = 'ended'
    await flushPromises()
    expect(view.text()).toContain('这个范围内暂无活动')
  })
})
