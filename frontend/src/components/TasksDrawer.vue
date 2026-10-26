<script setup lang="ts">
import { useAppStore } from '../store'
const store = useAppStore()
const labels: Record<string, string> = { running: '进行中', succeeded: '完成', failed: '未完成', cancelled: '已取消' }
const colors: Record<string, string> = { running: 'processing', succeeded: 'success', failed: 'error', cancelled: 'default' }
</script>
<template>
  <a-drawer v-model:open="store.taskDrawer" title="任务与日志" :width="560">
    <a-empty v-if="!store.tasks.length" description="还没有操作记录"/>
    <section v-for="task in store.tasks" :key="task.id" class="task-card"><header><strong>{{ task.label }}</strong><a-tag :color="colors[task.state]">{{ labels[task.state] }}</a-tag></header><small class="muted">{{ task.startedAt.replace('T', ' ') }}</small><div class="task-log"><div v-for="(entry, index) in task.logs" :key="index"><time>{{ entry.time.slice(11) }}</time><span>{{ entry.message }}</span></div></div></section>
  </a-drawer>
</template>
