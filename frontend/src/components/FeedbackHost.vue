<script setup lang="ts">
import { CheckCircleFilled, CloseCircleFilled, ExclamationCircleFilled, InfoCircleFilled, CloseOutlined } from '@ant-design/icons-vue'
import { dismissNotice, notices } from '../feedback'
const icons = { success: CheckCircleFilled, error: CloseCircleFilled, warning: ExclamationCircleFilled, info: InfoCircleFilled }
</script>
<template>
  <Teleport to="body"><TransitionGroup name="stella-notice" tag="div" class="stella-notices" aria-live="polite" aria-relevant="additions removals"><div v-for="notice in notices" :key="notice.id" class="stella-notice" :data-tone="notice.tone" :role="notice.tone === 'error' ? 'alert' : 'status'"><component :is="icons[notice.tone]" aria-hidden="true"/><span>{{ notice.text }}</span><button aria-label="关闭提示" @click="dismissNotice(notice.id)"><CloseOutlined aria-hidden="true"/></button></div></TransitionGroup></Teleport>
</template>
