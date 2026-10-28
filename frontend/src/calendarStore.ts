import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { CalendarSnapshot } from './types'

export const useCalendarStore = defineStore('calendar', () => {
  const data = ref<CalendarSnapshot>({ items: [], updatedAt: 0, loading: false, stale: false, error: '', offline: false,
    source: '星塔旅人国服官网', sourceUrl: 'https://stellasora.yostar.cn' })
  const filter = ref('active')
  const selectedId = ref<number | null>(null)
  const connectionError = ref('')
  async function load() {
    try {
      data.value = await window.stella.request<CalendarSnapshot>('calendar.get')
      connectionError.value = ''
    } catch (error) { connectionError.value = String((error as Error).message || error) }
  }
  async function refresh(force = false) {
    if (data.value.loading) return
    data.value.loading = true
    try {
      await window.stella.request('calendar.refresh', { force })
      await load()
    } catch (error) {
      data.value.loading = false
      connectionError.value = String((error as Error).message || error)
    }
  }
  async function openArticle(id?: number) {
    try {
      await window.stella.request(id === undefined ? 'shell.openCalendarSite' : 'shell.openCalendarArticle', id === undefined ? {} : { id })
    } catch (error) { connectionError.value = String((error as Error).message || error) }
  }
  return { data, filter, selectedId, connectionError, load, refresh, openArticle }
})
