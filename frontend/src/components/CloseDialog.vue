<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import AppDialog from './AppDialog.vue'
import { useAppStore } from '../store'
import { message } from '../feedback'
const store = useAppStore()
const pending = ref(false)
const open = computed(() => !!store.closePrompt)
const copy = computed(() => store.closePrompt?.reason === 'update'
  ? { title: '更新还在下载，要退出吗？', text: '退出会停止本次未完成的下载。下次打开软件后，你可以重新下载；已保存的招募记录和设置不会丢失。' }
  : store.closePrompt?.reason === 'busy'
    ? { title: '正在完成操作', text: '当前任务仍在读取或保存数据，请完成后再退出。你可以打开任务与日志查看进度。' }
    : { title: '后台还未结束', text: '后台正在结束操作，或暂时没有响应。请稍后重试；任务与日志中保留了最近的操作信息。' })
async function respond(action: 'stay'|'logs'|'exit') {
  if (!store.closePrompt || pending.value) return
  const id = store.closePrompt.id
  pending.value = true
  try {
    await window.stella.request('app.closeRespond', { id, action })
    if (store.closePrompt?.id === id) store.closePrompt = null
    if (action === 'logs') store.taskDrawer = true
  } catch (error) { message.error((error as Error).message) }
  finally { pending.value = false }
}
function escape(event: KeyboardEvent) {
  if (event.key === 'Escape' && store.closePrompt && !pending.value) {
    event.preventDefault(); event.stopImmediatePropagation(); void respond('stay')
  }
}
onMounted(() => document.addEventListener('keydown', escape, true))
onUnmounted(() => document.removeEventListener('keydown', escape, true))
</script>
<template>
  <AppDialog :open="open" :title="copy.title" :variant="store.closePrompt?.reason === 'update' ? 'danger' : 'info'" :footer="null" :z-index="2000" :closable="!pending" :keyboard="!pending" @cancel="respond('stay')" class="close-dialog">
    <p class="stella-dialog-description">{{ copy.text }}</p><div v-if="store.activeTask" class="stella-context-card"><span>当前任务</span><strong>{{ store.activeTask.label }}</strong><small>{{ store.activeTask.logs.at(-1)?.message }}</small></div>
    <div class="dialog-actions"><template v-if="store.closePrompt?.reason === 'update'"><a-button :disabled="pending" @click="respond('stay')">继续下载</a-button><a-button danger type="primary" :loading="pending" @click="respond('exit')">停止并退出</a-button></template><template v-else><a-button :disabled="pending" @click="respond('stay')">返回软件</a-button><a-button type="primary" :loading="pending" @click="respond('logs')">查看任务与日志</a-button></template></div>
  </AppDialog>
</template>
