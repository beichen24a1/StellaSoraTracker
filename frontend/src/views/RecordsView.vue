<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAppStore } from '../store'
import { avatar, date, number } from '../format'
import type { Pool, Pull, QueryResult, RecordRow } from '../types'
const store = useAppStore()
const result = ref<QueryResult>({ items: [], page: 1, pageSize: 10, total: 0 })
const loading = ref(false)
let generation = 0
let timer: ReturnType<typeof setTimeout> | undefined
const filter = computed(() => store.recordsFilter)
const filters = computed(() => [{ key: 'all', name: '全部卡池' }, ...(store.state?.summary.categories || []).map(c => ({ key: c.key, name: c.name })), ...(store.state?.summary.activity.length ? [{ key: 'activity', name: '活动卡池' }] : [])])
const pools = computed(() => result.value.items as Pool[])
const rows = computed(() => result.value.items as RecordRow[])
const summary = computed(() => store.state?.summary)
// This is a visual scale only. All record intervals and statistics come from Python.
const intervalScale = computed(() => pools.value.reduce((scale, pool) =>
  (pool.entries || []).reduce((value, pull) => Math.max(value, Math.ceil((pull.interval || 0) / 20) * 20), scale), 80))
function intervalTone(pull: Pull) {
  if (pull.reward) return 'reward'
  if (!pull.interval) return 'unknown'
  return pull.interval <= 20 ? 'short' : pull.interval <= 50 ? 'medium' : 'long'
}
function intervalWidth(pull: Pull) { return (Math.min(1, (pull.interval || 0) / intervalScale.value) * 100) + '%' }
function dateTime(time: number) { const value = new Date(time * 1000); return Number.isNaN(value.getTime()) ? undefined : value.toISOString() }
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
  <section class="page records-page"><div class="page-heading"><div><h1>招募记录</h1><p class="muted">按卡池回看每一次相遇，五星间隔一目了然。</p></div><a-button :disabled="store.busy || !store.state?.summary.pulls" @click="store.exportRecords()">导出 JSON / CSV</a-button></div>
    <div class="record-summary" aria-label="当前账号累计统计"><div><span>账号累计</span><strong>{{ number(summary?.pulls || 0) }}<small>抽</small></strong></div><div><span>五星记录</span><strong>{{ number(summary?.five || 0) }}<small>次</small></strong></div><div><span>五星概率</span><strong>{{ number(summary?.rate || 0) }}<small>%</small></strong></div><div><span>平均五星抽数</span><strong>{{ number(summary?.average) }}<small>抽</small></strong></div></div>
    <div class="records-toolbar"><div class="filter-pills"><button v-for="item in filters" :key="item.key" :class="{ active: filter.category === item.key && !filter.gid }" @click="category(item.key)">{{ item.name }}</button></div><div class="record-controls"><a-input-search v-model:value="filter.query" placeholder="搜索名称或卡池" allow-clear @change="filter.page = 1" aria-label="搜索记录"/><a-segmented :value="filter.mode" :options="[{ label: '五星记录', value: 'five' }, { label: '全部记录', value: 'all' }]" @change="mode"/><a-select v-model:value="filter.ascending" :options="[{label:'时间倒序',value:false},{label:'时间正序',value:true}]" aria-label="记录排序"/></div></div>
    <div class="records-caption"><span>五星间隔按任意五星重置，同类卡池间连续计算；奖励不计抽数。</span><a-tag v-if="filter.gid" closable @close="filter.gid = null; filter.fiveOnly = false">卡池 {{ filter.gid }} · 仅五星</a-tag><span>{{ number(result.total) }} {{ filter.mode === 'five' ? '个卡池' : '条记录' }}</span></div>
    <div v-if="filter.mode === 'five' && pools.length" class="interval-legend"><span>五星间隔</span><span><i class="short"></i>1–20 抽</span><span><i class="medium"></i>21–50 抽</span><span><i class="long"></i>51 抽及以上</span><small>本页色条刻度 0–{{ intervalScale }} 抽</small></div>
    <a-spin :spinning="loading">
      <div v-if="filter.mode === 'five' && pools.length" class="pool-grid" :style="{ '--pool-columns': store.state?.preferences.pool_columns || 'auto' }" :class="{ 'single-column': store.state?.preferences.pool_columns === 1, 'two-columns': store.state?.preferences.pool_columns === 2 }">
        <article v-for="pool in pools" :key="pool.gid" class="panel pool-card">
          <header class="history-pool-heading">
            <div class="history-pool-title"><div class="history-pool-name"><h2>{{ pool.name }}</h2><span v-if="pool.activity" class="pool-kind">活动</span><a-tag v-if="pool.well" color="gold">井 · 120 抽达成</a-tag></div><small class="muted">{{ pool.start || date(pool.lastTime) }}<span v-if="pool.end"> — {{ pool.end }}</span><span class="pool-id">ID {{ pool.gid }}</span></small><span class="pool-five-count">{{ pool.five }} 次五星</span></div>
            <div class="pool-total" :aria-label="'本池累计 '+pool.pulls+' 抽'"><small>本池累计</small><span><strong>{{ number(pool.pulls) }}</strong>抽</span></div>
          </header>
          <ol v-if="pool.entries.length" class="pull-history" :aria-label="pool.name+'的五星记录'">
            <li v-for="(pull, index) in pool.entries" :key="index" class="history-row" :class="'interval-'+intervalTone(pull)">
              <div class="history-portrait"><a-avatar shape="square" :size="40" :src="avatar(pull.itemId, pull.kind)">{{ pull.name.slice(0, 1) }}</a-avatar><span v-if="pull.result === 'UP'" class="portrait-up">UP</span></div>
              <div class="history-detail"><div class="history-label"><strong>{{ pull.name }}</strong><span v-if="pull.reward || pull.result === '歪'" class="history-result" :class="{'is-off':pull.result === '歪','is-reward':pull.reward}">{{ pull.reward ? '兑换奖励' : pull.result }}</span><time :datetime="dateTime(pull.time)">{{ date(pull.time) }}</time></div>
                <div v-if="!pull.reward" class="interval-track" role="img" :aria-label="pull.name+'，五星间隔 '+(pull.interval ?? '待确认')+' 抽；色条上限 '+intervalScale+' 抽'"><span class="interval-lane" aria-hidden="true"><span class="interval-fill" :style="{width: intervalWidth(pull)}"></span></span><span class="interval-value" aria-hidden="true"><strong>{{ pull.interval ?? '—' }}</strong><small>抽</small></span></div>
                <div v-else class="reward-line">120 抽兑换 · 不计入抽数与五星间隔</div>
              </div>
            </li>
          </ol>
          <p v-else class="muted pool-empty">此卡池已有归档，暂未获得五星。</p>
          <a-button v-if="(pool.entriesTotal || 0) > pool.entries.length" type="link" class="history-more" @click="more(pool)">查看全部 {{ pool.entriesTotal }} 条五星记录 →</a-button>
        </article>
      </div>
      <a-table v-else-if="filter.mode === 'all'" :columns="columns" :data-source="rows" row-key="key" :pagination="false" :scroll="{ x: 800 }" class="record-table" size="middle"><template #bodyCell="{ column, record }"><span v-if="column.key === 'time'">{{ date(record.time) }}</span><span v-else-if="column.key === 'name'" class="record-name"><a-avatar shape="square" :size="32" :src="avatar(record.itemId, record.kind)">{{ record.name.slice(0,1) }}</a-avatar>{{ record.name }}</span><a-tag v-else-if="column.key === 'five'" :color="record.five ? 'gold' : undefined">{{ record.five ? '五星' : '普通' }}</a-tag><a-tag v-else-if="column.key === 'result'" :color="record.result === 'UP' ? 'blue' : undefined">{{ record.result }}</a-tag><span v-else-if="column.key === 'interval'">{{ record.interval ? record.interval+' 抽' : '—' }}</span></template></a-table>
      <a-empty v-else description="没有符合条件的记录，试试清除搜索或先抓取游戏记录。" class="records-empty"/>
    </a-spin>
    <div v-if="result.total" class="pagination-row"><a-pagination :current="result.page" :page-size="filter.pageSize" :total="result.total" :show-size-changer="false" show-less-items @change="page"/></div>
  </section>
</template>

<style scoped>
.records-page { max-width: 1480px; --history-short: #33b49a; --history-medium: #d4a251; --history-long: #df7569; --history-off: #b8574d; --history-reward: #a87a2b; --history-tint: 8%; }
:global(:root[data-theme="dark"] .records-page) { --history-short: #45bfa3; --history-medium: #e2b65f; --history-long: #e28376; --history-off: #f1a397; --history-reward: #e6c47f; --history-tint: 12%; }
.record-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); background: var(--surface); border: 1px solid var(--line); border-radius: 11px; padding: 15px 0; margin-bottom: 22px; }
.record-summary > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 20px; border-right: 1px solid var(--line); }
.record-summary > div:last-child { border-right: 0; }
.record-summary > div > span { font-size: 11px; color: var(--muted); }
.record-summary strong { color: var(--text); font-size: 23px; font-weight: 650; font-variant-numeric: tabular-nums; white-space: nowrap; }
.record-summary strong small { font-size: 10px; font-weight: 400; margin-left: 5px; color: var(--muted); }
.interval-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 15px; color: var(--muted); font-size: 10px; margin: 0 0 13px; }
.interval-legend > span { display: inline-flex; align-items: center; gap: 5px; }
.interval-legend i { width: 7px; height: 7px; border-radius: 2px; }
.interval-legend .short { background: var(--history-short); }.interval-legend .medium { background: var(--history-medium); }.interval-legend .long { background: var(--history-long); }
.interval-legend > small { font-size: 10px; margin-left: auto; }
.pool-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 680px), 1fr)); gap: 14px; align-items: start; }
.pool-grid.single-column { grid-template-columns: 1fr; }
.pool-grid.two-columns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.pool-card { padding: 17px 20px 7px; overflow: hidden; }
.pool-card > .history-pool-heading { display: flex; flex-wrap: nowrap; align-items: center; gap: 15px; padding-bottom: 13px; margin-bottom: 0; }
.history-pool-title { flex: 1; min-width: 0; }
.history-pool-name { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 7px; }
.history-pool-name h2 { margin: 0; font-size: 15px; overflow-wrap: anywhere; }
.history-pool-name .ant-tag { font-size: 10px; margin: 0; line-height: 19px; }
.pool-kind { font-size: 9px; border: 1px solid var(--line); color: var(--muted); border-radius: 4px; padding: 1px 5px; }
.pool-id { margin-left: 12px; opacity: .75; }
.pool-five-count { font-size: 10px; color: var(--muted); margin-left: 12px; white-space: nowrap; }
.pool-total { display: flex; flex-direction: column; align-items: flex-end; justify-content: center; gap: 4px; min-width: 72px; border-radius: 7px; background: var(--primary-soft); color: var(--primary); padding: 9px 12px; flex-shrink: 0; }
.pool-total > small { font-size: 9px; }.pool-total > span { font-size: 10px; white-space: nowrap; }.pool-total strong { font-size: 23px; line-height: 1; font-weight: 680; font-variant-numeric: tabular-nums; margin-right: 4px; }
.pull-history { list-style: none; padding: 0; margin: 0; }
.history-row { display: flex; align-items: center; gap: 11px; padding: 11px 0; border-bottom: 1px solid var(--line); --interval-color: var(--history-short); }
.history-row:last-child { border-bottom: 0; }
.interval-medium { --interval-color: var(--history-medium); }.interval-long { --interval-color: var(--history-long); }.interval-unknown { --interval-color: var(--muted); }
.history-portrait { position: relative; width: 40px; height: 40px; flex-shrink: 0; }.history-portrait .ant-avatar { border-radius: 7px; background: var(--surface-2); color: var(--muted); }
.portrait-up { position: absolute; bottom: -2px; right: -3px; font-size: 8px; line-height: 13px; padding: 0 3px; border-radius: 3px; color: var(--surface); background: var(--primary); border: 1px solid var(--surface); font-weight: 650; }
.history-detail { flex: 1; min-width: 0; }
.history-label { display: flex; align-items: center; gap: 7px; min-height: 18px; margin-bottom: 5px; }
.history-label > strong { font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-label > time { font-size: 9px; color: var(--muted); margin-left: auto; white-space: nowrap; }
.history-result { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: var(--primary-soft); color: var(--primary); white-space: nowrap; }
.history-result.is-off { background: color-mix(in srgb, var(--history-long) 10%, transparent); color: var(--history-off); }.history-result.is-reward { background: color-mix(in srgb, var(--history-medium) 10%, transparent); color: var(--history-reward); }
.interval-track { display: flex; align-items: center; height: 24px; gap: 8px; }
.interval-lane { position: relative; display: block; flex: 1; height: 24px; border-radius: 4px; background: color-mix(in srgb, var(--interval-color) var(--history-tint), transparent); overflow: hidden; }
.interval-fill { position: absolute; inset: 0 auto 0 0; background: var(--interval-color); opacity: .72; border-radius: inherit; transform-origin: left; }
.interval-value { display: inline-flex; align-items: baseline; justify-content: flex-end; min-width: 45px; gap: 4px; line-height: 24px; color: var(--text); font-variant-numeric: tabular-nums; }
.interval-value > strong { font-size: 14px; font-weight: 700; }.interval-value > small { font-size: 9px; }
.reward-line { font-size: 10px; color: var(--muted); background: var(--surface-2); border: 1px dashed var(--line); border-radius: 4px; min-height: 24px; padding: 4px 8px; }
.history-more { margin: 0 0 6px 40px; font-size: 11px; }
.pool-card:nth-child(-n+4) .history-row:nth-child(-n+6) .interval-fill { animation: interval-grow 380ms var(--motion-ease) backwards; }
@keyframes interval-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@media (max-width: 1150px) { .record-summary > div { flex-direction: column; align-items: flex-start; gap: 5px; padding: 0 15px; }.record-summary strong { font-size: 21px; }.pool-card { padding-inline: 16px; }.history-pool-name h2 { font-size: 14px; }.pool-five-count { display: block; margin: 4px 0 0; }.interval-legend { gap: 10px; } }
</style>
