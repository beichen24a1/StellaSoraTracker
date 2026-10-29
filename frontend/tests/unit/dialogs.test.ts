import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import { useAppStore } from '../../src/store'
import type { AppState } from '../../src/types'
import CloseDialog from '../../src/components/CloseDialog.vue'
import UpdateDialog from '../../src/components/UpdateDialog.vue'
import FeedbackHost from '../../src/components/FeedbackHost.vue'
import { notices, dismissNotice, message } from '../../src/feedback'

let request: ReturnType<typeof vi.fn>
let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  setActivePinia(createPinia())
  request = vi.fn(async () => ({ ok: true }))
  window.stella = { request, onEvent: () => () => {} }
  useAppStore().state = { version: '1.3.0.bata4', accounts: [], preferences: { color_mode: 'light' }, busy: false } as unknown as AppState
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; useAppStore().$dispose(); for (const item of [...notices]) dismissNotice(item.id); document.body.innerHTML = '' })
const component = (value: any) => { wrapper = mount(value, { attachTo: document.body, global: { plugins: [Antd] } }); return wrapper }
async function click(text: string) { const button = [...document.querySelectorAll('button')].find(value => value.textContent?.replace(/\s/g, '') === text)!; expect(button).toBeTruthy(); button.click(); await flushPromises() }

it('continuing a download leaves the app open and sends the matching prompt ID', async () => {
  const store = useAppStore(); store.closePrompt = { id: 'prompt-1', reason: 'update' }
  component(CloseDialog)
  await flushPromises(); await click('继续下载')
  expect(request).toHaveBeenCalledWith('app.closeRespond', { id: 'prompt-1', action: 'stay' })
  expect(store.closePrompt).toBeNull()
})
it('does not clear a newer busy prompt when an exit acknowledgement arrives', async () => {
  const store = useAppStore(); store.closePrompt = { id: 'old', reason: 'update' }
  request.mockImplementation(async () => { store.closePrompt = { id: 'new', reason: 'busy' }; return { ok: true } })
  component(CloseDialog)
  await flushPromises(); await click('停止并退出')
  expect(store.closePrompt?.id).toBe('new')
  expect(document.body.textContent).toContain('正在完成操作')
})
it('cancel download requires an explicit designed confirmation', async () => {
  const store = useAppStore(); store.updateOpen = true; store.update = { status: 'downloading', received: 100, total: 200 }
  component(UpdateDialog)
  await flushPromises(); await click('取消下载')
  expect(document.body.textContent).toContain('取消这次下载？')
  expect(request).not.toHaveBeenCalled()
  await click('继续下载')
  expect(request).not.toHaveBeenCalled()
  await click('取消下载')
  const confirm = [...document.querySelectorAll('.ant-modal')].find(value => value.textContent?.includes('取消这次下载？'))!
  const button = [...confirm.querySelectorAll('button')].find(value => value.textContent?.replace(/\s/g, '') === '取消下载')!
  button.click(); await flushPromises()
  expect(request).toHaveBeenCalledWith('updates.cancel', {})
})
it('deduplicates repeated error events into a dismissible themed notice', async () => {
  for (const item of [...notices]) dismissNotice(item.id)
  component(FeedbackHost)
  message.error('保存失败'); message.error('保存失败')
  await flushPromises()
  expect(document.querySelectorAll('.stella-notice')).toHaveLength(1)
  expect(document.querySelector('[role="alert"]')?.textContent).toContain('保存失败')
  ;(document.querySelector('button[aria-label="关闭提示"]') as HTMLButtonElement).click()
  await flushPromises()
  expect(notices).toHaveLength(0)
})
