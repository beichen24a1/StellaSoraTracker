import type { CalendarEntry } from './types'

export type CalendarPhase = 'ongoing' | 'upcoming' | 'ended' | 'maintenance'
export const kindLabel = { version: '版本活动', event: '限时活动', permanent: '常驻活动', recruit: '限时招募' }
export const phaseLabel: Record<CalendarPhase, string> = { ongoing: '进行中', upcoming: '即将开始', ended: '已结束', maintenance: '维护后开启' }
export function phase(item: CalendarEntry, now: number): CalendarPhase {
  if (now >= item.endAt) return 'ended'
  if (now < item.startAt) return 'upcoming'
  // The official announcement gives a date but no maintenance completion time.
  if (item.startApproximate && now < item.startAt + 86400) return 'maintenance'
  return 'ongoing'
}
export function countdown(item: CalendarEntry, now: number): string {
  const status = phase(item, now)
  if (status === 'ended') return '活动已结束'
  if (status === 'maintenance') return '以游戏维护进度为准'
  if (status === 'upcoming' && item.startApproximate) return '维护结束后开启'
  const seconds = Math.max(0, (status === 'upcoming' ? item.startAt : item.endAt) - now)
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor(seconds % 86400 / 3600)
  const minutes = Math.floor(seconds % 3600 / 60)
  return days ? `${days} 天 ${hours} 时` : hours ? `${hours} 时 ${minutes} 分` : minutes ? `${minutes} 分` : '不足 1 分钟'
}
export function calendarDate(stamp: number, withTime = true): string {
  const date = new Date(stamp * 1000)
  const text = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } as const : {}) }).format(date)
  return text
}
export function startLabel(item: CalendarEntry): string {
  return calendarDate(item.startAt, !item.startApproximate) + (item.startApproximate ? ' 维护后' : '')
}
export function chooseFeatured(items: CalendarEntry[], now: number): CalendarEntry | undefined {
  return [...items].sort((a, b) => {
    const rank = (item: CalendarEntry) => (phase(item, now) === 'ended' ? 20 : phase(item, now) === 'upcoming' ? 10 : 0)
      + ({ version: 0, event: 1, permanent: 2, recruit: 3 }[item.kind])
    return rank(a) - rank(b) || b.startAt - a.startAt
  })[0]
}
