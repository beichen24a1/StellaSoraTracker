<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAppStore } from '../store'
import { avatar, date, number } from '../format'
import type { Pool, QueryResult, RecordRow } from '../types'
const store = useAppStore()
const result = ref<QueryResult>({ items: [], page: 1, pageSize: 10, total: 0 })
const loading = ref(false)
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined
const filter = computed(() => store.recordsFilter)
const filters = computed(() => [{ key: 'all', name: '全部卡池' }, ...(store.state?.summary.categories || []).map(c => ({ key: c.key, name: c.name })), ...(store.state?.summary.activity.length ? [{ key: 'activity', name: '活动卡池' }] : [])])
const pools = computed(() => result.value.items as Pool[])
const rows = computed(() => result.value.items as RecordRow[])
const columns = [
  { title: '日期', dataIndex: 'time', key: 'time', width: 125 }, { title: '旅人 / 秘纹', dataIndex: 'name', key: 'name' },
  { title: '稀有度', dataIndex: 'five', key: 'five', width: 85 }, { title: '所属卡池', dataIndex: 'poolName', key: 'poolName' },
  { title: '结果', dataIndex: 'result', key: 'result', width: 80 }, { title: '五星间隔', dataIndex: 'interval', key: 'interval', width: 100 },
]
async function load() {
  const current = ++generation
  loading.value = true
  const value = await store.invoke<QueryResult>('records.query', { ...filter.value })
  if (current !== generation) return
  if (value) result.value = value
  loading.value = false
}
watch(() => JSON.stringify(store.recordsFilter), () => { clearTimeout(timer); timer = setTimeout(() => void load(), 180) }, { immediate: true })
watch(() => store.state?.summary, () => void load())
function category(key: string) { Object.assign(store.recordsFilter, { category: key, page: 1, gid: null, fiveOnly: false }) }
function page(value: number) { store.recordsFilter.page = value }
function mode(value: string | number) { Object.assign(store.recordsFilter, { mode: String(value), page: 1, pageSize: value === 'five' ? 10 : 50 }) }
function more(pool: Pool) { Object.assign(store.recordsFilter, { mode: 'all', category: 'all', gid: pool.gid, fiveOnly: true, page: 1, pageSize: 50 }) }
</script>
<template>
  <section class="page records-page"><div class="page-heading"><div><h1>招募记录</h1><p class="muted">把相遇按时间归档，也把每一次幸运看清楚。</p></div><a-button :disabled="store.busy || !store.state?.summary.pulls" @click="store.exportRecords()">导出 JSON / CSV</a-button></div>
    <div class="records-toolbar"><div class="filter-pills"><button v-for="item in filters" :key="item.key" :class="{ active: filter.category === item.key && !filter.gid }" @click="category(item.key)">{{ item.name }}</button></div><div class="record-controls"><a-input-search v-model:value="filter.query" placeholder="搜索名称或卡池" allow-clear @change="filter.page = 1" aria-label="搜索记录"/><a-segmented :value="filter.mode" :options="[{ label: '五星记录', value: 'five' }, { label: '全部记录', value: 'all' }]" @change="mode"/><a-select v-model:value="filter.ascending" :options="[{label:'时间倒序',value:false},{label:'时间正序',value:true}]" aria-label="记录排序"/></div></div>
    <div class="records-caption"><span>五星间隔按任意五星重置，奖励记录只展示、不计入抽数。</span><a-tag v-if="filter.gid" closable @close="filter.gid = null; filter.fiveOnly = false">卡池 {{ filter.gid }} · 仅五星</a-tag><span>{{ number(result.total) }} {{ filter.mode === 'five' ? '个卡池' : '条记录' }}</span></div>
    <a-spin :spinning="loading">
      <div v-if="filter.mode === 'five' && pools.length" class="pool-grid" :style="{ '--pool-columns': store.state?.preferences.pool_columns || 'auto' }" :class="{ 'single-column': store.state?.preferences.pool_columns === 1, 'two-columns': store.state?.preferences.pool_columns === 2 }">
        <article v-for="pool in pools" :key="pool.gid" class="panel pool-card"><header><div><h2>{{ pool.name }}</h2><small class="muted">{{ pool.start || date(pool.lastTime) }} <span v-if="pool.end"> — {{ pool.end }}</span> · ID {{ pool.gid }}</small></div><div class="pool-badges"><a-tag v-if="pool.well" color="gold">井 · 120 抽达成</a-tag><span>{{ pool.pulls }} 抽 / {{ pool.five }} 五星</span></div></header><div v-if="pool.entries.length" class="pull-grid"><div v-for="(pull, index) in pool.entries" :key="index" class="pull-entry"><a-avatar shape="square" :size="52" :src="avatar(pull.itemId, pull.kind)">{{ pull.name.slice(0, 1) }}</a-avatar><div><strong>{{ pull.name }}</strong><small>{{ pull.reward ? '井 · 120 抽奖励' : '五星间隔 '+pull.interval+' 抽' }}</small><time>{{ date(pull.time) }}</time></div><a-tag v-if="pull.result !== '—'" :color="pull.reward ? 'gold' : pull.result === 'UP' ? 'blue' : 'default'">{{ pull.result }}</a-tag></div></div><p v-else class="muted pool-empty">此卡池已有归档，暂未获得五星。</p><a-button v-if="(pool.entriesTotal || 0) > pool.entries.length" type="link" @click="more(pool)">查看全部 {{ pool.entriesTotal }} 条五星记录 →</a-button></article>
      </div>
      <a-table v-else-if="filter.mode === 'all'" :columns="columns" :data-source="rows" row-key="key" :pagination="false" :scroll="{ x: 800 }" class="record-table" size="middle"><template #bodyCell="{ column, record }"><span v-if="column.key === 'time'">{{ date(record.time) }}</span><span v-else-if="column.key === 'name'" class="record-name"><a-avatar shape="square" :size="32" :src="avatar(record.itemId, record.kind)">{{ record.name.slice(0,1) }}</a-avatar>{{ record.name }}</span><a-tag v-else-if="column.key === 'five'" :color="record.five ? 'gold' : undefined">{{ record.five ? '五星' : '普通' }}</a-tag><a-tag v-else-if="column.key === 'result'" :color="record.result === 'UP' ? 'blue' : undefined">{{ record.result }}</a-tag><span v-else-if="column.key === 'interval'">{{ record.interval ? record.interval+' 抽' : '—' }}</span></template></a-table>
      <a-empty v-else description="没有符合条件的记录，试试清除搜索或先抓取游戏记录。" class="records-empty"/>
    </a-spin>
    <div v-if="result.total" class="pagination-row"><a-pagination :current="result.page" :page-size="filter.pageSize" :total="result.total" :show-size-changer="false" show-less-items @change="page"/></div>
  </section>
</template>
