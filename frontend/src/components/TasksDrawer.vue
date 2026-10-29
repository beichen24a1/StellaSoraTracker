<script setup lang="ts">
import { useAppStore } from '../store'
import { HistoryOutlined } from '@ant-design/icons-vue'
const store = useAppStore()
const labels: Record<string, string> = { running: '进行中', succeeded: '完成', failed: '未完成', cancelled: '已取消' }
const colors: Record<string, string> = { running: 'processing', succeeded: 'success', failed: 'error', cancelled: 'default' }
</script>
<template>
  <a-drawer v-model:open="store.taskDrawer" :width="560" class="stella-task-drawer"><template #title><div class="stella-dialog-heading"><div class="stella-dialog-mark"><HistoryOutlined aria-hidden="true"/></div><div><small aria-hidden="true">STELLA SORA</small><h2>任务与日志</h2></div></div></template>
    <a-empty v-if="!store.tasks.length" description="还没有操作记录"/>
    <TransitionGroup name="task-list" tag="div" class="task-list"><section v-for="task in store.tasks" :key="task.id" class="task-card"><header><strong>{{ task.label }}</strong><a-tag :color="colors[task.state]">{{ labels[task.state] }}</a-tag></header><small class="muted">{{ task.startedAt.replace('T', ' ') }}</small><div class="task-log"><div v-for="(entry, index) in task.logs" :key="index"><time>{{ entry.time.slice(11) }}</time><span>{{ entry.message }}</span></div></div></section></TransitionGroup>
  </a-drawer>
</template>
