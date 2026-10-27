<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { ReloadOutlined, StarFilled, HeartOutlined } from '@ant-design/icons-vue'
import { useAppStore } from '../store'

const store = useAppStore()

const running = computed(() => store.tasks.find(task => task.label === '读取好感度' && task.state === 'running'))
const status = computed(() => running.value?.logs.at(-1)?.message || '')
const entries = computed(() => store.affinity)
const updatedLabel = computed(() => {
  if (!store.affinityUpdated) return '尚未读取'
  const value = new Date(store.affinityUpdated)
  return Number.isNaN(value.getTime()) ? store.affinityUpdated : value.toLocaleString('zh-CN', { hour12: false })
})
const topLevel = computed(() => entries.value.reduce((best, item) => Math.max(best, item.level), 0))

function percent(item: { ratio: number }) {
  return Math.max(0, Math.min(100, Math.round((item.ratio || 0) * 100)))
}

onMounted(() => { void store.loadAffinity() })
// 好感度按账号单独存放: 切账号后重新读该账号的 affinity.json
watch(() => store.state?.activeAccount, () => { void store.loadAffinity(true) })
</script>

<template>
  <section class="page affinity-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">角色羁绊 · 只读</div>
        <h1>旅人好感度</h1>
        <p class="muted">读取游戏内存里已经加载的角色数据，单独保存，不改动抽卡归档。</p>
      </div>
      <a-button type="primary" :loading="store.affinityBusy" :disabled="store.busy" @click="store.capture('affinity.read')">
        <ReloadOutlined v-if="!store.affinityBusy" aria-hidden="true"/> 读取好感度
      </a-button>
    </div>

    <div class="affinity-meta panel">
      <div class="meta-item"><span>已读取</span><strong>{{ entries.length }}</strong><small>位旅人</small></div>
      <div class="meta-item"><span>最高好感</span><strong>{{ topLevel || '—' }}</strong><small>级</small></div>
      <div class="meta-note">
        <span class="uid-line"><strong>UID</strong> {{ store.affinityUid || '未确认' }}</span>
        <small>{{ status || `上次读取：${updatedLabel}` }}</small>
        <small :title="store.affinityPath">单独存放：{{ store.affinityPath || 'exports/affinity/<UID>.json' }}</small>
      </div>
    </div>

    <div v-if="!entries.length" class="panel empty-guide">
      <div class="empty-symbol"><HeartOutlined aria-hidden="true"/></div>
      <h2>还没有好感度数据</h2>
      <p class="muted">登录游戏后点右上角「读取好感度」。游戏没开时这里会显示上次保存的结果。</p>
    </div>

    <div v-else class="affinity-grid">
      <article v-for="item in entries" :key="item.id" class="affinity-card">
        <img class="avatar" :src="`app://assets/travelers/${item.id}.png`" alt=""
             @error="($event.target as HTMLImageElement).style.visibility = 'hidden'">
        <div class="body">
          <div class="line">
            <strong>{{ item.name }}</strong>
            <StarFilled v-if="item.favorite" class="favorite" title="已收藏" />
            <span class="level">Lv.{{ item.level }}</span>
          </div>
          <div class="bar"><i :style="{ width: percent(item) + '%' }"></i></div>
          <div class="numbers">
            <span>{{ item.exp.toLocaleString('zh-CN') }}<em v-if="item.need"> / {{ item.need.toLocaleString('zh-CN') }}</em></span>
            <span v-if="item.need">{{ percent(item) }}%</span>
            <span v-else>—</span>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.affinity-meta{display:flex;align-items:center;gap:34px;padding:20px 24px;margin-bottom:22px;flex-wrap:wrap}
.meta-item{display:flex;align-items:baseline;gap:6px;color:var(--muted);font-size:11px}
.meta-item strong{font-size:23px;font-weight:620;color:var(--text);font-variant-numeric:tabular-nums}
.meta-item small{color:var(--muted)}
.meta-note{margin-left:auto;text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:5px;font-size:11px;color:var(--text);max-width:46%}
.meta-note .uid-line{font-size:12px;font-variant-numeric:tabular-nums}
.meta-note .uid-line strong{color:var(--primary);font-weight:600;margin-right:3px}
.meta-note small{color:var(--muted);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.affinity-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.affinity-card{display:flex;align-items:center;gap:13px;background:var(--surface);border:1px solid var(--line);border-radius:11px;padding:13px 15px;box-shadow:var(--shadow)}
.avatar{width:44px;height:44px;border-radius:10px;object-fit:cover;background:var(--surface-2);flex-shrink:0}
.body{flex:1;min-width:0}
.line{display:flex;align-items:center;gap:7px;margin-bottom:7px}
.line strong{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.favorite{color:#e3a94f;font-size:11px}
.level{margin-left:auto;font-size:11px;color:var(--primary);background:var(--primary-soft);border-radius:6px;padding:2px 8px;font-variant-numeric:tabular-nums}
.bar{height:5px;border-radius:3px;background:var(--surface-2);overflow:hidden}
.bar i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--primary),#8ec9e6);transition:width .25s ease}
.numbers{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:6px;font-variant-numeric:tabular-nums}
.numbers em{font-style:normal}
@media(max-width:1150px){.affinity-grid{grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}.meta-note{margin-left:0;text-align:left}}
</style>
