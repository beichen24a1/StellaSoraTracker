<script setup lang="ts">
import { computed, ref } from 'vue'
import { message } from '../feedback'
import { CheckCircleOutlined, CloudSyncOutlined, CloudUploadOutlined, CopyOutlined, InfoCircleOutlined, LinkOutlined } from '@ant-design/icons-vue'
import { useAppStore } from '../store'
import { number } from '../format'

const store = useAppStore()
const savingHhmx = ref(false)
const savingProgress = ref(false)
const syncingProgress = ref(false)
const autoUploadHhmx = computed(() => Boolean(store.state?.preferences.auto_upload_hhmx))
const offline = computed(() => Boolean(store.state?.offline))
const canUpload = computed(() => Boolean(store.state?.summary.uid && store.state.summary.pulls && !store.state.offline))
const autoUploadState = computed(() => autoUploadHhmx.value ? '已开启' : '已关闭')
const autoUploadNote = computed(() => {
  if (savingHhmx.value) return '正在保存 hhmx.cn 自动上传设置…'
  if (offline.value) return autoUploadHhmx.value
    ? '当前离线，自动上传到 hhmx.cn 会在恢复在线并下次抓取或导入时生效。'
    : '离线模式下不会上传；恢复在线后可在这里开启 hhmx.cn 自动上传。'
  if (autoUploadHhmx.value) return '下次成功抓取或导入后会直接上传到 hhmx.cn；这不会改变蕾姆自动上传。'
  return '默认关闭，只控制 hhmx.cn；蕾姆自动上传仍由「数据与设置」单独管理。'
})

async function copyBind() {
  const value = await store.invoke('shell.copyBind')
  if (value) message.success('绑定指令已复制')
}

async function setAutoUploadHhmx(value: unknown) {
  if (savingHhmx.value) return
  const next = value === true
  if (next === autoUploadHhmx.value) return
  savingHhmx.value = true
  try {
    await store.savePreferences({ auto_upload_hhmx: next })
    if (autoUploadHhmx.value === next) message.success(next ? '已开启自动上传到 hhmx.cn' : '已关闭 hhmx.cn 自动上传')
  } finally {
    savingHhmx.value = false
  }
}

async function setAutoUploadProgress(value: unknown) {
  if (savingProgress.value) return
  savingProgress.value = true
  try {
    await store.savePreferences({ auto_upload_hhmx_progress: value === true })
  } finally {
    savingProgress.value = false
  }
}

async function syncProgress() {
  syncingProgress.value = true
  try {
    if (await store.invoke('hhmx.sync')) message.success('已将当前 UID 的现有数据同步到 hhmx.cn')
  } finally {
    syncingProgress.value = false
  }
}
</script>

<template>
  <section class="page upload-page">
    <div class="page-heading">
      <div>
        <h1>上传与分享</h1>
        <p class="muted">把已核对的记录交给蕾姆或 hhmx.cn，与你的招募档案保持同步。</p>
      </div>
    </div>

    <div class="panel upload-summary">
      <div class="upload-icon"><CloudUploadOutlined aria-hidden="true" /></div>
      <div>
        <span class="eyebrow">当前账号归档</span>
        <h2>{{ store.state?.summary.uid ? 'UID ' + store.state.summary.uid : '尚未设置 UID' }}</h2>
        <p class="muted">{{ number(store.state?.summary.groups || 0) }} 组记录 · {{ number(store.state?.summary.pulls || 0) }} 抽</p>
      </div>
      <a-button type="primary" size="large" :loading="store.busy" :disabled="!store.state?.summary.uid || !store.state.summary.pulls || store.state.offline" @click="store.invoke('upload.send')">上传到蕾姆</a-button>
    </div>

    <section class="panel auto-upload-panel" :class="{ 'is-on': autoUploadHhmx }">
      <div class="auto-upload-head">
        <div class="auto-upload-intro">
          <div class="auto-upload-mark"><CloudSyncOutlined aria-hidden="true" /></div>
          <div>
            <div class="auto-upload-title">
              <h2>自动上传到 <span>hhmx.cn</span></h2>
              <span class="auto-upload-badge" :class="{ 'is-on': autoUploadHhmx }"><i></i>{{ autoUploadState }}</span>
            </div>
            <p>抓取或导入成功后，自动上传当前 UID 的抽卡记录。相同记录会跳过，蕾姆的上传开关独立管理。</p>
          </div>
        </div>
        <div class="auto-upload-toggle">
          <a-switch
            :checked="autoUploadHhmx"
            :loading="savingHhmx"
            :disabled="!store.state || savingHhmx"
            aria-label="自动上传到 hhmx.cn"
            @change="setAutoUploadHhmx"
          />
        </div>
      </div>
      <div class="auto-upload-facts">
        <span><small>目标站点</small><strong>hhmx.cn</strong></span>
        <span><small>触发时机</small><strong>抓取 / 导入成功后</strong></span>
        <span><small>绑定方式</small><strong>不需要蕾姆指令</strong></span>
      </div>
      <div class="auto-upload-footer">
        <p class="auto-upload-note" aria-live="polite">
          <InfoCircleOutlined aria-hidden="true" />
          <span>{{ autoUploadNote }}</span>
        </p>
        <a-space class="auto-upload-actions" wrap>
          <a-button size="small" :loading="store.busy" :disabled="store.busy || !canUpload" @click="store.invoke('upload.sendHhmx')">上传到 hhmx.cn</a-button>
          <a-button size="small" type="link" @click="store.invoke('shell.openExports')">打开数据目录</a-button>
          <a-button size="small" type="link" @click="store.invoke('shell.manualUploadHhmx')">前往 hhmx.cn 手动导入</a-button>
        </a-space>
      </div>
    </section>

    <section class="panel auto-upload-panel" :class="{ 'is-on': store.state?.preferences.auto_upload_hhmx_progress }">
      <div class="auto-upload-head">
        <div class="auto-upload-intro">
          <div class="auto-upload-mark"><CloudSyncOutlined aria-hidden="true" /></div>
          <div>
            <div class="auto-upload-title"><h2>好感度和角色数据同步</h2></div>
            <p>首次请打开站点账号页面并绑定游戏 UID。开启后，每次成功读取好感度或角色数据都会自动同步。</p>
          </div>
        </div>
        <a-switch :checked="!!store.state?.preferences.auto_upload_hhmx_progress"
                  :loading="savingProgress" :disabled="!store.state || savingProgress"
                  aria-label="自动同步好感度和角色数据到 hhmx.cn" @change="setAutoUploadProgress"/>
      </div>
      <div class="auto-upload-footer">
        <p class="auto-upload-note">可立即同步当前 UID 已保存的数据。</p>
        <a-space class="auto-upload-actions" wrap>
          <a-button size="small" :disabled="offline" @click="store.invoke('hhmx.account')">打开 hhmx.cn 账号页面</a-button>
          <a-button size="small" type="primary" :loading="syncingProgress"
                    :disabled="!store.state?.summary.uid || offline" @click="syncProgress">立即同步</a-button>
        </a-space>
      </div>
    </section>

    <section class="panel binding-panel">
      <div class="section-label">
        <h2><CheckCircleOutlined aria-hidden="true" />上传到蕾姆后，还需要确认绑定</h2>
        <p>上传到蕾姆成功表示归档已暂存。每次更新后，仍需向蕾姆发送下面的指令确认；hhmx.cn 不需要这条指令。</p>
      </div>
      <div class="bind-command">{{ store.state?.bindCommand || '请先读取或保存有效 UID' }}</div>
      <a-space wrap>
        <a-button :disabled="!store.state?.bindCommand" @click="copyBind"><CopyOutlined aria-hidden="true" />复制绑定指令</a-button>
        <a-button @click="store.invoke('shell.manualUpload')"><LinkOutlined aria-hidden="true" />打开蕾姆手动上传页</a-button>
        <a-button :disabled="store.busy || !store.state?.summary.pulls" @click="store.invoke('records.share')">导出分享文件</a-button>
      </a-space>
    </section>

    <div class="upload-footnote">
      <strong>分享前，先确认账号</strong>
      <p>分享文件名与内容必须属于同一 UID。工具会在上传与导出前校验，不会将别人的归档改成当前账号。</p>
      <p>上传到蕾姆或 hhmx.cn 失败都不会改动本地归档，可以稍后重试。</p>
    </div>
  </section>
</template>
