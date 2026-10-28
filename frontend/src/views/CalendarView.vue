<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { CalendarOutlined, ReloadOutlined, ExportOutlined, ClockCircleOutlined, ArrowRightOutlined } from '@ant-design/icons-vue'
import { useCalendarStore } from '../calendarStore'
import { calendarDate, chooseFeatured, countdown, kindLabel, phase, phaseLabel, startLabel } from '../calendar'
import type { CalendarEntry } from '../types'

const store = useCalendarStore()
const now = ref(Date.now() / 1000)
const visible = computed(() => store.data.items.filter(item => {
  const status = phase(item, now.value)
  return store.filter === 'all' || (store.filter === 'active' ? status !== 'ended' : status === store.filter)
}).sort((a, b) => (phase(a, now.value) === 'ended' ? 2 : phase(a, now.value) === 'upcoming' ? 1 : 0)
  - (phase(b, now.value) === 'ended' ? 2 : phase(b, now.value) === 'upcoming' ? 1 : 0) || a.endAt - b.endAt))
const featured = computed(() => visible.value.find(item => item.id === store.selectedId) || chooseFeatured(visible.value, now.value))
const permanent = computed(() => visible.value.filter(item => item.kind === 'permanent'))
const status = (item: CalendarEntry) => phase(item, now.value)
const remainingLabel = (item: CalendarEntry) => status(item) === 'upcoming' ? '距离开启' : status(item) === 'ended' ? '活动状态' : '距离结束'
let unsubscribe: (() => void) | undefined
let ticker: ReturnType<typeof setInterval> | undefined
onMounted(async () => {
  unsubscribe = window.stella.onEvent(event => {
    if (event.name === 'calendar') { store.data = event.payload; store.connectionError = '' }
  })
  ticker = setInterval(() => { now.value = Date.now() / 1000 }, 30000)
  await store.load()
  void store.refresh()
})
onUnmounted(() => { unsubscribe?.(); if (ticker) clearInterval(ticker) })
</script>

<template>
  <section class="page calendar-page">
    <div class="page-heading calendar-heading">
      <div><div class="eyebrow">STELLA SORA · EVENTS</div><h1>活动日历</h1><p class="muted">把握每一段旅程。活动时间均为北京时间（UTC+8）。</p></div>
      <div class="calendar-actions"><a-button @click="store.openArticle()"><ExportOutlined aria-hidden="true"/> 国服官网</a-button><a-button type="primary" :loading="store.data.loading" @click="store.refresh(true)"><ReloadOutlined v-if="!store.data.loading" aria-hidden="true"/>刷新活动</a-button></div>
    </div>
    <div class="calendar-source"><span class="calendar-source-dot"></span><strong>国服官网活动</strong><span>独立于当前账号与服务器</span><time v-if="store.data.updatedAt">{{ store.data.stale ? '缓存于' : '更新于' }} {{ calendarDate(store.data.updatedAt) }}</time><span v-else>首次进入时同步官网公告</span></div>
    <a-alert v-if="store.connectionError || store.data.error" class="calendar-alert" type="warning" show-icon :message="store.connectionError || store.data.error"/>

    <div v-if="store.data.loading && !store.data.items.length" class="calendar-loading panel" role="status"><a-spin size="large"/><h2>正在整理活动日程</h2><p class="muted">读取官网公告，并将活动封面保存到本地。</p></div>
    <div v-else-if="!store.data.items.length" class="calendar-loading panel"><CalendarOutlined class="calendar-empty-icon"/><h2>暂时没有可显示的活动</h2><p class="muted">联网刷新后即可查看日程，也可以直接前往国服官网。</p><a-button @click="store.refresh(true)">重新获取</a-button></div>
    <div v-else class="calendar-layout">
      <div class="calendar-main">
        <Transition name="calendar-feature" mode="out-in">
          <article v-if="featured" :key="featured.id" class="calendar-hero" :class="{ 'calendar-no-cover': !featured.cover }" aria-label="当前活动详情">
            <img v-if="featured.cover" :src="featured.cover" class="calendar-hero-image" alt="" @error="($event.target as HTMLImageElement).style.visibility = 'hidden'">
            <div class="calendar-hero-shade"></div>
            <div class="calendar-hero-content">
              <div class="calendar-hero-tags"><span class="calendar-phase" :data-phase="status(featured)">{{ phaseLabel[status(featured)] }}</span><span class="calendar-kind">{{ kindLabel[featured.kind] }}</span></div>
              <h2>{{ featured.name }}</h2><p class="calendar-hero-description">{{ featured.description }}</p>
              <button class="calendar-article-link" @click="store.openArticle(featured.id)">查看活动公告 <ArrowRightOutlined aria-hidden="true"/></button>
            </div>
            <div class="calendar-hero-bottom"><div class="calendar-range"><ClockCircleOutlined/><span>{{ startLabel(featured) }}<br>{{ calendarDate(featured.endAt - 1) }} 结束</span></div><div class="calendar-countdown"><small>{{ remainingLabel(featured) }}</small><strong>{{ countdown(featured, now) }}</strong></div></div>
          </article>
          <div v-else class="calendar-no-results panel"><CalendarOutlined/><h2>这个范围内暂无活动</h2><p class="muted">可以切换日程范围，查看其他活动。</p><a-button @click="store.filter = 'active'">查看当前活动</a-button></div>
        </Transition>
        <section class="panel calendar-permanent"><div class="calendar-section-heading"><h2>常驻活动</h2><span class="muted">周期开放 · 留意本期结束时间</span></div>
          <div v-if="permanent.length" class="calendar-permanent-grid"><button v-for="item in permanent" :key="item.id" class="calendar-mini" :class="{ selected: featured?.id === item.id }" @click="store.selectedId = item.id">
            <img v-if="item.cover" :src="item.cover" alt="" loading="lazy"><div class="calendar-mini-shade"></div><div class="calendar-mini-content"><span class="calendar-phase" :data-phase="status(item)">{{ phaseLabel[status(item)] }}</span><strong>{{ item.name }}</strong><div><span>{{ countdown(item, now) }}</span><small>{{ calendarDate(item.endAt - 1, false) }} 结束</small></div></div>
          </button></div><p v-else class="calendar-permanent-empty muted">{{ store.filter !== 'active' ? '当前筛选下没有常驻活动。' : '官网近期公告中没有可识别的常驻活动时间。' }}</p>
        </section>
        <p class="calendar-footnote muted">活动信息整理自国服官网公告；开放时间、奖励与规则以游戏内及官方公告为准。招募记录与账号数据不会上传至官网。</p>
      </div>
      <aside class="calendar-schedule panel" aria-label="活动日程">
        <div class="calendar-section-heading"><h2>活动日程 <span>{{ visible.length }}</span></h2><CalendarOutlined/></div>
        <div class="calendar-filters"><a-select v-model:value="store.filter" aria-label="日程范围" :options="[{value:'active',label:'当前与即将开启'}, {value:'upcoming',label:'即将开启'}, {value:'ended',label:'近期结束'}, {value:'all',label:'全部日程'}]"/></div>
        <div class="calendar-schedule-list"><button v-for="item in visible" :key="item.id" class="calendar-schedule-card" :class="{ selected: featured?.id === item.id }" :aria-pressed="featured?.id === item.id" :aria-label="item.title" @click="store.selectedId = item.id">
          <img v-if="item.cover" :src="item.cover" alt="" loading="lazy"><div class="calendar-mini-shade"></div><div class="calendar-schedule-content"><div><span class="calendar-phase" :data-phase="status(item)">{{ phaseLabel[status(item)] }}</span><small class="calendar-kind">{{ kindLabel[item.kind] }}</small></div><h3>{{ item.name }}</h3><p>{{ item.title }}</p><footer><strong>{{ countdown(item, now) }}</strong><span>{{ status(item) === 'upcoming' ? startLabel(item) + ' 开启' : calendarDate(item.endAt - 1) + ' 结束' }}</span></footer></div>
        </button><p v-if="!visible.length" class="calendar-list-empty muted">没有符合条件的日程</p></div>
      </aside>
    </div>
  </section>
</template>

<style src="../calendar.css"></style>
