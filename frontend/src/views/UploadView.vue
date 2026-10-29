<script setup lang="ts">
import { message } from '../feedback'
import { CloudUploadOutlined, CopyOutlined, LinkOutlined, CheckCircleOutlined } from '@ant-design/icons-vue'
import { useAppStore } from '../store'
import { number } from '../format'
const store = useAppStore()
async function copyBind() { const value = await store.invoke('shell.copyBind'); if(value) message.success('绑定指令已复制') }
</script>
<template>
  <section class="page upload-page"><div class="page-heading"><div><h1>上传与分享</h1><p class="muted">把已核对的记录交给蕾姆，与你的招募档案保持同步。</p></div></div><div class="panel upload-summary"><div class="upload-icon"><CloudUploadOutlined aria-hidden="true"/></div><div><span class="eyebrow">当前账号归档</span><h2>{{ store.state?.summary.uid ? 'UID '+store.state.summary.uid : '尚未设置 UID' }}</h2><p class="muted">{{ number(store.state?.summary.groups || 0) }} 组记录 · {{ number(store.state?.summary.pulls || 0) }} 抽</p></div><a-button type="primary" size="large" :loading="store.busy" :disabled="!store.state?.summary.uid || !store.state.summary.pulls || store.state.offline" @click="store.invoke('upload.send')">上传到蕾姆</a-button></div><section class="panel binding-panel"><div class="section-label"><h2><CheckCircleOutlined aria-hidden="true"/>上传后，还需要确认绑定</h2><p>上传成功表示归档已暂存。每次更新后，仍需向蕾姆发送下面的指令确认。</p></div><div class="bind-command">{{ store.state?.bindCommand || '请先读取或保存有效 UID' }}</div><a-space wrap><a-button :disabled="!store.state?.bindCommand" @click="copyBind"><CopyOutlined aria-hidden="true"/>复制绑定指令</a-button><a-button @click="store.invoke('shell.manualUpload')"><LinkOutlined aria-hidden="true"/>打开手动上传网页</a-button><a-button :disabled="store.busy || !store.state?.summary.pulls" @click="store.invoke('records.share')">导出分享文件</a-button></a-space></section><a-alert type="info" show-icon message="自动上传可在“数据与设置”开启，默认关闭。上传失败不影响已经保存的本地归档。"/><div class="upload-footnote"><strong>分享前，先确认账号</strong><p>分享文件名与内容必须属于同一 UID。工具会在上传与导出前校验，不会将别人的归档改成当前账号。</p></div></section>
</template>
