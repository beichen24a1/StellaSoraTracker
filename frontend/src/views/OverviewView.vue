<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRightOutlined, CloudUploadOutlined, DownloadOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'
import { useAppStore } from '../store'
import { number, date } from '../format'
const store = useAppStore()
const router = useRouter()
const summary = computed(() => store.state?.summary)
const account = computed(() => store.state?.accounts.find(value => value.key === store.state?.activeAccount))
function records(category: string) { store.recordsFilter.category = category; store.recordsFilter.page = 1; void router.push('/records') }
</script>
<template>
  <section class="page overview-page">
    <div class="page-heading"><div><div class="eyebrow">我的招募档案</div><h1>每一次相遇，都有记录。</h1><p class="muted">{{ account?.name || (summary?.uid ? 'UID '+summary.uid : '默认账号') }}<span class="dot-separator">·</span>{{ date(summary?.firstTime) }}<span v-if="summary?.pulls"> — {{ date(summary?.lastTime) }}</span></p></div><a-button @click="store.invoke('archive.backup')" :disabled="store.busy || !summary?.pulls"><SafetyCertificateOutlined aria-hidden="true"/>创建备份</a-button></div>
    <div class="metrics-grid"><div class="metric-card"><span>累计抽取</span><strong>{{ number(summary?.pulls || 0) }}<small>抽</small></strong><p>{{ number(summary?.groups || 0) }} 批已保存记录</p></div><div class="metric-card"><span>五星相遇</span><strong>{{ number(summary?.five || 0) }}<small>次</small></strong><p>只统计真实抽卡结果</p></div><div class="metric-card"><span>五星概率</span><strong>{{ number(summary?.rate || 0) }}<small>%</small></strong><p>基于当前完整本地归档</p></div><div class="metric-card"><span>平均五星抽数</span><strong>{{ number(summary?.average) }}<small>抽</small></strong><p>五星总数与累计抽取计算</p></div></div>
    <div class="section-heading"><div><h2>各类招募</h2><p class="muted">这里展示 UP 保底进度，记录页保留任意五星间隔。</p></div><a-button type="link" @click="records('all')">浏览全部记录 <ArrowRightOutlined aria-hidden="true"/></a-button></div>
    <div class="category-grid"><button v-for="(category, index) in summary?.categories" :key="category.key" class="category-card" @click="records(category.key)"><header><span class="category-mark" :class="'mark-'+index">{{ category.name.slice(0, 2) }}</span><h3>{{ category.name }}</h3><ArrowRightOutlined aria-hidden="true"/></header><div class="category-count"><strong>{{ number(category.pulls) }}</strong><span>抽 / {{ category.five }} 五星</span></div><div class="pity-label"><span>当前垫抽</span><strong>{{ category.pity }} <small>/ {{ category.limit }}</small></strong></div><a-progress :percent="Math.min(100, category.pity / category.limit * 100)" :show-info="false"/><footer><span>平均 {{ number(category.average) }} 抽 / 五星</span><span>{{ category.pulls ? '查看卡池 →' : '等待读取' }}</span></footer></button></div>
    <div v-if="summary?.activity.length" class="panel activity-summary"><div class="section-heading"><h2>活动卡池</h2><a-button type="link" @click="records('activity')">查看活动 <ArrowRightOutlined aria-hidden="true"/></a-button></div><button v-for="pool in summary.activity" :key="pool.gid" @click="records('activity')"><span>{{ pool.name }}</span><strong>{{ number(pool.pulls) }} 抽</strong><small>{{ pool.five_stars }} 五星</small></button></div>
    <div v-if="!summary?.pulls" class="panel empty-guide"><div class="empty-symbol"><DownloadOutlined aria-hidden="true"/></div><h2>从第一份招募记录开始</h2><p class="muted">在游戏里打开各类招募记录后抓取，或导入已有的 JSON / CSV 文件。</p><a-space><a-button type="primary" @click="store.capture()" :disabled="store.busy">抓取抽卡记录</a-button><a-button @click="store.importFiles()">导入记录</a-button></a-space></div>
    <div class="overview-bottom"><SafetyCertificateOutlined aria-hidden="true"/><span>记录保存在你的电脑，按 UID 独立归档。</span><a-button type="link" @click="router.push('/upload')"><CloudUploadOutlined aria-hidden="true"/>上传与分享</a-button></div>
  </section>
</template>
