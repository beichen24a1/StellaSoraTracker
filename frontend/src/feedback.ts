import { reactive } from 'vue'

type Tone = 'success'|'error'|'warning'|'info'
export const notices = reactive<{ id: number; tone: Tone; text: string }[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let next = 0
export function dismissNotice(id: number) {
  clearTimeout(timers.get(id)); timers.delete(id)
  const index = notices.findIndex(item => item.id === id)
  if (index >= 0) notices.splice(index, 1)
}
function show(tone: Tone, content: unknown) {
  const text = String(content ?? '').slice(0, 1200)
  if (!text) return
  const existing = notices.find(item => item.tone === tone && item.text === text)
  if (existing) { clearTimeout(timers.get(existing.id)); timers.set(existing.id, setTimeout(() => dismissNotice(existing.id), tone === 'error' ? 7000 : 4000)); return }
  if (notices.length >= 4) dismissNotice(notices[0]!.id)
  const id = ++next
  notices.push({ id, tone, text })
  timers.set(id, setTimeout(() => dismissNotice(id), tone === 'error' ? 7000 : 4000))
}
export const message = { success: (text: unknown) => show('success', text), error: (text: unknown) => show('error', text),
  warning: (text: unknown) => show('warning', text), info: (text: unknown) => show('info', text) }
