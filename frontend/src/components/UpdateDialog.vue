<script setup lang="ts">
import AppDialog from './AppDialog.vue'
import { computed, ref, watch } from 'vue'
import { CloudDownloadOutlined, CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons-vue'
import { useAppStore } from '../store'
import { bytes, duration } from '../format'
const store = useAppStore()
const cancelOpen = ref(false)
const downloading = computed(() => ['downloading', 'verifying'].includes(store.update.status))
const stage = computed(() => downloading.value ? 'download' : store.update.status)
const percent = computed(() => store.update.total ? Math.min(100, (store.update.received || 0) / store.update.total * 100) : 0)
function later() { store.updateOpen = false }
watch(downloading, value => { if (!value) cancelOpen.value = false })
async function cancelDownload() {
  const result = await store.invoke('updates.cancel')
  if (result !== undefined) cancelOpen.value = false
}
</script>
<template>
  <AppDialog v-model:open="store.updateOpen" transition-name="stella-dialog" mask-transition-name="stella-mask" :width="680" :footer="null" :mask-closable="false" title="软件更新" variant="update" class="update-modal">
    <div class="update-heading"><div class="update-symbol"><CloudDownloadOutlined aria-hidden="true"/></div><div><h2>{{ store.update.status === 'ready' ? '更新已就绪' : store.update.update ? '发现新版本' : '检查更新' }}</h2><p class="muted">{{ store.state?.version }} <span v-if="store.update.update"> → {{ store.update.update.version }}</span></p></div><a-tag>{{ (store.update.channel || store.state?.preferences.update_channel) === 'beta' ? '测试渠道' : '稳定渠道' }}</a-tag></div>
    <Transition name="update-stage" mode="out-in"><div :key="stage" class="update-stage">
    <template v-if="store.update.status === 'available'">
      <div class="release-notes"><h3>本次更新</h3><pre>{{ store.update.update?.notes || '本次暂无详细更新说明。' }}</pre></div>
      <p class="muted">下载后校验 SHA-256，安装前仍需你确认。</p>
      <div class="dialog-actions"><a-button @click="later">暂不更新</a-button><a-button type="primary" @click="store.invoke('updates.download')">下载更新</a-button></div>
    </template>
    <template v-else-if="downloading">
      <div class="download-box"><div class="download-title"><strong>{{ store.update.status === 'verifying' ? '正在校验文件' : '正在下载更新' }}</strong><strong>{{ percent.toFixed(1) }}%</strong></div><a-progress :percent="percent" :show-info="false"/><div class="download-metrics"><span>{{ bytes(store.update.received) }} / {{ store.update.total ? bytes(store.update.total) : '未知大小' }}</span><span>{{ bytes(store.update.speed) }}/s</span><span>预计剩余 {{ duration(store.update.eta) }}</span></div><small class="muted">下载来源：GitHub</small></div>
      <div class="dialog-actions"><a-button danger @click="cancelOpen = true">取消下载</a-button><a-button type="primary" ghost @click="later">后台下载</a-button></div>
    </template>
    <template v-else-if="store.update.status === 'ready'">
      <div class="update-result"><CheckCircleFilled class="success-icon"/><h3>下载完成，文件校验通过</h3><p>本地归档与设置会保留。你也可以稍后从“数据与设置”安装。</p><a-alert v-if="store.busy" type="info" message="正在完成当前操作，结束后可安装更新。"/></div><div class="dialog-actions"><a-button @click="later">稍后安装</a-button><a-button type="primary" :disabled="store.busy || !store.state?.packaged" @click="store.invoke('updates.install')">立即安装并重启</a-button></div><p v-if="!store.state?.packaged" class="muted">当前为开发预览，不能替换正式程序。</p>
    </template>
    <template v-else-if="store.update.status === 'failed' || store.update.status === 'cancelled'">
      <div class="update-result"><CloseCircleFilled class="error-icon"/><h3>{{ store.update.status === 'cancelled' ? '下载已取消' : '更新未完成' }}</h3><p>{{ store.update.error || '你可以稍后重新下载。' }}</p></div><div class="dialog-actions"><a-button @click="later">关闭</a-button><a-button type="primary" @click="store.invoke(store.update.update ? 'updates.download' : 'updates.check')">重试</a-button></div>
    </template>
    <template v-else><a-spin v-if="store.update.status === 'checking'" tip="正在检查…"/><a-result v-else-if="store.update.status === 'upToDate'" status="success" title="当前已是最新版本"/><p v-else class="muted">等待更新检查结果。</p><div class="dialog-actions"><a-button @click="later">关闭</a-button></div></template>
    </div></Transition>
  </AppDialog>
  <AppDialog v-model:open="cancelOpen" title="取消这次下载？" variant="danger" :footer="null" :z-index="1600"><p class="stella-dialog-description">未完成的下载文件会被删除。你可以稍后重新下载，本地招募归档和设置不会受到影响。</p><div class="stella-context-card"><span>当前下载</span><strong>{{ store.update.update?.version || '软件更新' }}</strong><small>{{ bytes(store.update.received) }} / {{ store.update.total ? bytes(store.update.total) : '未知大小' }}</small></div><div class="dialog-actions"><a-button @click="cancelOpen = false">继续下载</a-button><a-button danger type="primary" @click="cancelDownload">取消下载</a-button></div></AppDialog>
</template>
