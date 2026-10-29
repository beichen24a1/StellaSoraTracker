<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { IdcardOutlined } from '@ant-design/icons-vue'
import catalogue from '../emblems.json'
import type { RosterEmblem } from '../types'

const props = defineProps<{ emblem: Pick<RosterEmblem, 'icon' | 'name'> }>()
// Match game icon paths first; names support old caches without sIcon.
// Unknown emblems never borrow a different emblem's picture or load a remote URL.
const source = computed(() => {
  const icon = props.emblem.icon?.replace(/\.png$/i, '')
  const item = catalogue.items.find(item => icon && item.icon === icon)
    || catalogue.items.find(item => item.name === props.emblem.name)
  return item ? `app://assets/emblems/${item.id}.png` : ''
})
const failed = ref(false)
watch(source, () => { failed.value = false })
</script>

<template>
  <span class="emblem-thumbnail" aria-hidden="true">
    <img v-if="source && !failed" :src="source" alt="" @error="failed = true">
    <IdcardOutlined v-else class="emblem-placeholder"/>
  </span>
</template>

<style scoped>
.emblem-thumbnail{display:inline-flex;align-items:center;justify-content:center;width:48px;height:48px;flex:none;border-radius:8px;background:var(--surface);border:1px solid var(--line);padding:5px;overflow:hidden}
.emblem-thumbnail img{display:block;width:100%;height:100%;object-fit:contain}
.emblem-placeholder{font-size:22px;color:var(--muted)}
</style>
