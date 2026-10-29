<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowRightOutlined, HistoryOutlined, IdcardOutlined, HeartOutlined, SettingOutlined, CloudUploadOutlined, QuestionCircleOutlined, CalendarOutlined } from '@ant-design/icons-vue'
import { useAppStore } from '../store'
import { useCalendarStore } from '../calendarStore'
import { chooseFeatured, phase, phaseLabel, countdown, calendarDate } from '../calendar'
import { avatar, number, date } from '../format'
import type { HomeSummary } from '../types'

const store = useAppStore()
const calendar = useCalendarStore()
const account = computed(() => store.state?.accounts.find(item => item.key === store.state?.activeAccount))
const owner = computed(() => JSON.stringify([store.state?.activeAccount, account.value?.uid || '']))
const data = ref<HomeSummary | null>(null)
const error = ref('')
const loading = ref(false)
const now = ref(Date.now() / 1000)
const events = computed(() => calendar.data.items.filter(item => phase(item, now.value) !== 'ended'))
const featured = computed(() => chooseFeatured(events.value, now.value))
const nextEvents = computed(() => events.value.filter(item => item.id !== featured.value?.id).sort((a, b) => a.endAt - b.endAt).slice(0, 2))
const collections = computed(() => [
  { key: 'roster', title: '角色数据', to: '/roster', action: '查看角色', icon: IdcardOutlined, data: data.value?.roster },
  { key: 'affinity', title: '好感度', to: '/affinity', action: '查看好感度', icon: HeartOutlined, data: data.value?.affinity },
])
let serial = 0
let alive = true
let timer: ReturnType<typeof setTimeout> | undefined
let ticker: ReturnType<typeof setInterval> | undefined
let unsubscribe: (() => void) | undefined
async function refresh() {
  if (!store.state) return
  const request = ++serial
  const context = owner.value
  loading.value = true
  try {
    const value = await window.stella.request<HomeSummary>('home.summary')
    if (!alive || request !== serial || context !== owner.value) return
    if (value.accountKey !== store.state.activeAccount || value.uid !== (account.value?.uid || '')) return
    data.value = value
    error.value = ''
  } catch (reason) {
    if (alive && request === serial) error.value = (reason as Error).message || String(reason)
  } finally { if (alive && request === serial) loading.value = false }
}
function savedAt(value?: string) {
  if (!value) return '尚未读取'
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? '已保存' : `更新于 ${time.toLocaleDateString('zh-CN')}`
}
watch(owner, () => { ++serial; data.value = null; error.value = ''; void refresh() }, { immediate: true, flush: 'sync' })
onMounted(() => {
  void calendar.load() // Read the shared calendar cache; game reads remain explicit actions.
  unsubscribe = window.stella.onEvent(event => {
    if (event.name === 'calendar') calendar.data = event.payload
    if (event.name === 'changed' || event.name === 'result') {
      clearTimeout(timer)
      timer = setTimeout(() => void refresh(), 80)
    }
  })
  ticker = setInterval(() => { now.value = Date.now() / 1000 }, 30000)
})
onUnmounted(() => { alive = false; ++serial; unsubscribe?.(); clearTimeout(timer); if (ticker) clearInterval(ticker) })
</script>

<template>
  <section class="page home-page">
    <div class="page-heading home-heading"><div><div class="eyebrow">STELLA SORA · MY ARCHIVE</div><h1>主页</h1><p class="muted">招募、养成与活动，在这里接着看。</p></div><a-button @click="store.taskDrawer = true"><HistoryOutlined aria-hidden="true"/>任务与日志<span v-if="store.activeTask" class="home-task-dot"></span></a-button></div>
    <section class="panel home-passport" aria-label="当前账号总览">
      <div class="home-passport-head"><div><span class="home-label">当前档案</span><h2>{{ account?.name || (account?.uid ? 'UID '+account.uid : '默认账号') }}</h2><p><span>{{ account?.uid ? 'UID '+account.uid : '尚未绑定 UID' }}</span><i></i><span>{{ store.state?.servers.find(item => item.key === store.state?.server)?.label || '正在连接' }}</span></p></div><router-link to="/settings" class="home-account-link">管理账号 <ArrowRightOutlined aria-hidden="true"/></router-link><div class="home-orbit" aria-hidden="true"><i></i><i></i><i></i><b>✦</b></div></div>
      <div class="home-stats"><router-link to="/overview"><span>累计抽取</span><strong>{{ number(store.state?.summary.pulls || 0) }}<small>抽</small></strong><span>招募总览 <ArrowRightOutlined aria-hidden="true"/></span></router-link><router-link to="/records"><span>五星相遇</span><strong>{{ number(store.state?.summary.five || 0) }}<small>次</small></strong><span>浏览记录 <ArrowRightOutlined aria-hidden="true"/></span></router-link><router-link to="/roster"><span>已读取旅人</span><strong>{{ data?.roster.available ? number(data.roster.count) : '—' }}<small>位</small></strong><span>{{ data?.roster.available ? '最高 Lv.'+data.roster.highestLevel : loading ? '正在读取摘要' : '尚未读取' }}</span></router-link><router-link to="/affinity"><span>最高好感度</span><strong>{{ data?.affinity.available ? data.affinity.highestLevel : '—' }}<small>级</small></strong><span>{{ data?.affinity.available ? data.affinity.count+' 位旅人的记录' : loading ? '正在读取摘要' : '尚未读取' }}</span></router-link></div>
    </section>
    <a-alert v-if="error" type="warning" show-icon class="home-error" :message="'部分摘要未能加载：'+error"><template #action><a-button size="small" aria-label="重新加载主页摘要" @click="refresh()">重试</a-button></template></a-alert>
    <div class="home-grid">
      <div class="home-main">
        <section class="panel home-recent"><header class="home-section-head"><div><h2>近期五星</h2><p class="muted">{{ store.state?.summary.lastTime ? '最近招募于 '+date(store.state.summary.lastTime) : '相遇记录会保存在本地' }}</p></div><router-link to="/records">查看记录 <ArrowRightOutlined aria-hidden="true"/></router-link></header>
          <div v-if="data?.recentFive.length" class="home-five-list" :style="{ gridTemplateColumns: `repeat(${Math.min(data.recentFive.length, 4)}, minmax(0, 1fr))` }"><article v-for="item in data.recentFive" :key="item.key" class="home-five-item"><div class="home-five-avatar"><img :src="avatar(item.itemId, item.kind)" alt="" @error="($event.target as HTMLImageElement).style.visibility = 'hidden'"><span>★★★★★</span></div><strong>{{ item.name }}</strong><small :title="item.poolName">{{ item.poolName }}</small><time>{{ date(item.time) }}</time></article></div>
          <div v-else class="home-empty"><p>{{ loading ? '正在读取相遇记录…' : store.state?.summary.pulls ? '当前归档还没有五星记录' : '从第一份招募记录开始' }}</p><span class="muted">{{ store.state?.summary.pulls ? '继续积累你的本地档案。' : '在游戏中打开招募记录后抓取，或导入已有文件。' }}</span><div v-if="!store.state?.summary.pulls" class="home-empty-actions"><a-button size="small" type="primary" :disabled="store.busy" @click="store.capture()">抓取抽卡记录</a-button><a-button size="small" :disabled="store.busy" @click="store.importFiles()">导入记录</a-button></div></div>
        </section>
        <div class="home-collections"><section v-for="item in collections" :key="item.key" class="panel home-collection" :data-kind="item.key"><header><component :is="item.icon" aria-hidden="true"/><h2>{{ item.title }}</h2><span>{{ item.data?.available ? '已保存' : '待读取' }}</span></header>
          <template v-if="item.data?.available"><div class="home-collection-value"><strong>{{ item.data.count }}</strong><span>位旅人</span><small>{{ item.key === 'roster' ? item.data.emblems+' 件纹章' : '最高 '+item.data.highestLevel+' 级' }}</small></div><div class="home-portraits"><div v-for="person in item.data.portraits" :key="person.id" :title="person.name+' · Lv.'+person.level"><img :src="`app://assets/travelers/${person.id}.png`" alt="" @error="($event.target as HTMLImageElement).style.visibility = 'hidden'"><span>{{ person.name }}</span><small>Lv.{{ person.level }}</small></div></div></template>
          <div v-else class="home-collection-empty"><p>{{ loading ? '正在读取摘要…' : item.data?.error || (item.key === 'roster' ? '还没有角色数据' : '还没有好感度记录') }}</p><span class="muted">{{ item.key === 'roster' ? '查看角色等级、技能、天赋与纹章。' : '查看旅人的好感等级与成长进度。' }}</span></div>
          <footer><span>{{ savedAt(item.data?.updatedAt) }}</span><router-link :to="item.to">{{ item.action }} <ArrowRightOutlined aria-hidden="true"/></router-link></footer>
        </section></div>
      </div>
      <section class="panel home-events"><header class="home-section-head"><div><h2>活动日程</h2><p class="muted">国服官网 · 北京时间</p></div><CalendarOutlined aria-hidden="true"/></header>
        <router-link v-if="featured" to="/calendar" class="home-event-cover"><img v-if="featured.cover" :src="featured.cover" alt=""><div></div><section><span>{{ phaseLabel[phase(featured, now)] }}</span><h3>{{ featured.name }}</h3><strong>{{ countdown(featured, now) }}</strong><small>{{ phase(featured, now) === 'upcoming' ? '距离开启' : '距离结束' }}</small></section></router-link>
        <div v-else class="home-event-empty"><CalendarOutlined aria-hidden="true"/><p>{{ calendar.data.updatedAt ? '近期暂无进行中的活动' : '还没有活动日程缓存' }}</p><small class="muted">进入活动日历，获取官网最新日程。</small></div>
        <div class="home-event-list"><router-link v-for="item in nextEvents" :key="item.id" to="/calendar"><span><strong>{{ item.name }}</strong><small>{{ phaseLabel[phase(item, now)] }}</small></span><b>{{ countdown(item, now) }}</b></router-link></div>
        <footer><span>{{ calendar.data.updatedAt ? '缓存于 '+calendarDate(calendar.data.updatedAt, false) : '日程与账号独立' }}</span><router-link to="/calendar">查看活动日历 <ArrowRightOutlined aria-hidden="true"/></router-link></footer>
      </section>
    </div>
    <nav class="home-shortcuts" aria-label="常用功能"><router-link to="/settings"><SettingOutlined aria-hidden="true"/><span>数据与设置<small>账号、备份、主题与更新</small></span><ArrowRightOutlined aria-hidden="true"/></router-link><router-link to="/upload"><CloudUploadOutlined aria-hidden="true"/><span>上传与分享<small>分享记录与绑定指令</small></span><ArrowRightOutlined aria-hidden="true"/></router-link><router-link to="/help"><QuestionCircleOutlined aria-hidden="true"/><span>使用说明<small>读取步骤与常见问题</small></span><ArrowRightOutlined aria-hidden="true"/></router-link></nav>
  </section>
</template>

<style src="../home.css"></style>
