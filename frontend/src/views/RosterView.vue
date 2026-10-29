<script setup lang="ts">
import AppDialog from '../components/AppDialog.vue'
import EmblemThumbnail from '../components/EmblemThumbnail.vue'
import { computed, onMounted, ref, watch } from 'vue'
import { ReloadOutlined, StarFilled, IdcardOutlined } from '@ant-design/icons-vue'
import { useAppStore } from '../store'
import type { RosterCharacter, RosterEmblem, RosterEmblemAttr } from '../types'

const store = useAppStore()
const detailId = ref<number | null>(null)
const FALLBACK_SLOTS = ['', '尖章', '方菱章', '星闪章']

const running = computed(() => store.tasks.find(task => task.label === '读取角色数据' && task.state === 'running'))
const status = computed(() => running.value?.logs.at(-1)?.message || '')
const characters = computed(() => [...store.roster].sort((left, right) =>
  Number(right.favorite) - Number(left.favorite)
  || right.level - left.level
  || left.id - right.id))
const updatedLabel = computed(() => {
  if (!store.rosterUpdated) return '尚未读取'
  const value = new Date(store.rosterUpdated)
  return Number.isNaN(value.getTime()) ? store.rosterUpdated : value.toLocaleString('zh-CN', { hour12: false })
})
const topLevel = computed(() => characters.value.reduce((best, item) => Math.max(best, item.level), 0))
const emblemCount = computed(() => characters.value.reduce((total, item) => total + item.emblems.length, 0))

function equippedEmblems(item: RosterCharacter) {
  return item.emblems.filter(emblem => emblem.active !== false)
}

function talentPercent(item: RosterCharacter) {
  if (!item.talent.max) return 0
  return Math.max(0, Math.min(100, Math.round((item.talent.active / item.talent.max) * 100)))
}

function slotName(item: RosterCharacter, slot: number) {
  return item.slots.find(entry => entry.slot === slot)?.name || FALLBACK_SLOTS[slot] || `槽位 ${slot}`
}

function slotUnlock(item: RosterCharacter, slot: number) {
  return item.slots.find(entry => entry.slot === slot)?.unlockLevel || 0
}

function slotEmblem(item: RosterCharacter, slot: number): RosterEmblem | undefined {
  return equippedEmblems(item).find(emblem => emblem.slot === slot)
}

function upgradeTotal(emblem: RosterEmblem) {
  return emblem.upgrades.reduce((total, value) => total + value, 0)
}

function formatValue(value: number) {
  if (!value) return '0'
  if (Math.abs(value) < 1) return `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`
  return value.toLocaleString('zh-CN')
}

const POTENTIAL_GROUPS = [
  ['master_specific', '主控专有'],
  ['master_normal', '主控通用'],
  ['assist_specific', '支援专有'],
  ['assist_normal', '支援通用'],
  ['common', '通用'],
] as const

function potentialGroups(item: RosterCharacter) {
  return POTENTIAL_GROUPS
    .map(([key, label]) => ({ key, label, names: item.potentials?.[key] || [] }))
    .filter(group => group.names.length)
}

function talentNames(item: RosterCharacter) {
  const seen = new Set<string>()
  return item.talent.names.filter(name => {
    if (seen.has(name)) return false
    seen.add(name)
    return true
  })
}

const detail = computed(() => characters.value.find(item => item.id === detailId.value) || null)
const detailOpen = computed({
  get: () => detail.value !== null,
  set: (value: boolean) => { if (!value) detailId.value = null },
})

function openDetail(item: RosterCharacter) {
  detailId.value = item.id
}

const emblemDetail = ref<{ owner: string; emblem: RosterEmblem } | null>(null)
const emblemOpen = computed({
  get: () => emblemDetail.value !== null,
  set: (value: boolean) => { if (!value) emblemDetail.value = null },
})

function openEmblemDetail(item: RosterCharacter, slot: number) {
  const emblem = slotEmblem(item, slot)
  if (emblem) emblemDetail.value = { owner: item.name, emblem }
}

function attrText(attr: RosterEmblemAttr) {
  const label = attr.name || `属性#${attr.attrId}`
  return `${label} ${formatValue(attr.value)}`
}

function affixNames(emblem: RosterEmblem) {
  return (emblem.affixNames || []).filter(Boolean)
}

onMounted(() => { void store.loadRoster() })
watch(() => JSON.stringify([store.state?.activeAccount, store.state?.accounts.find(account => account.key === store.state?.activeAccount)?.uid]), () => {
  detailId.value = null
  emblemDetail.value = null
})
</script>

<template>
  <section class="page roster-page">
    <div class="page-heading">
      <div>
        <div class="eyebrow">旅人养成 · 只读</div>
        <h1>角色数据</h1>
        <p class="muted">读取等级、突破、技能等级、天赋与纹章，单独保存，不改动抽卡归档。</p>
      </div>
      <a-button type="primary" :loading="store.rosterBusy" :disabled="store.busy" @click="store.capture('roster.read')">
        <ReloadOutlined v-if="!store.rosterBusy" aria-hidden="true"/> 读取角色数据
      </a-button>
    </div>

    <div class="roster-meta panel">
      <div class="meta-item"><span>已读取</span><strong>{{ characters.length }}</strong><small>位旅人</small></div>
      <div class="meta-item"><span>最高等级</span><strong>{{ topLevel || '—' }}</strong><small>级</small></div>
      <div class="meta-item"><span>纹章</span><strong>{{ emblemCount }}</strong><small>件</small></div>
      <div class="meta-note">
        <span class="uid-line"><strong>UID</strong> {{ store.rosterUid || '未确认' }}</span>
        <small>{{ status || `上次读取：${updatedLabel}` }}</small>
        <small :title="store.rosterPath">单独存放：{{ store.rosterPath || 'exports/<UID>_roster.json' }}</small>
      </div>
    </div>

    <div v-if="!characters.length" class="panel empty-guide">
      <div class="empty-symbol"><IdcardOutlined aria-hidden="true"/></div>
      <h2>还没有角色数据</h2>
      <p class="muted">登录游戏并打开一次「角色」和「纹章」界面，再点右上角「读取角色数据」。游戏没开时会显示上次保存的结果。</p>
    </div>

    <div v-else class="roster-grid">
      <article v-for="item in characters" :key="item.id" class="roster-card">
        <header class="card-head" @click="openDetail(item)">
          <img class="avatar" :src="`app://assets/travelers/${item.id}.png`" alt=""
               @error="($event.target as HTMLImageElement).style.visibility = 'hidden'">
          <div class="title">
            <strong>{{ item.name }}</strong>
            <span>Lv.{{ item.level }} · 突破 {{ item.advance }}</span>
          </div>
          <StarFilled v-if="item.favorite" class="favorite" title="已收藏" />
          <span class="chevron">详情</span>
        </header>

        <div class="skills">
          <span v-for="(level, index) in item.skills" :key="index" class="chip">技能{{ index + 1 }} <b>{{ level }}</b></span>
          <span v-if="!item.skills.length" class="chip muted">技能等级未读取</span>
        </div>

        <div class="talent">
          <div class="talent-head"><span>天赋</span><b>{{ item.talent.active }} / {{ item.talent.max || '—' }}</b></div>
          <div class="bar"><i :style="{ width: talentPercent(item) + '%' }"></i></div>
        </div>

        <div class="slots">
          <div v-for="slot in 3" :key="slot" class="slot"
               :class="{ clickable: !!slotEmblem(item, slot) }"
               @click.stop="openEmblemDetail(item, slot)">
            <small>{{ slotName(item, slot) }}</small>
            <template v-if="item.level < slotUnlock(item, slot)">
              <em>Lv.{{ slotUnlock(item, slot) }} 解锁</em>
            </template>
            <template v-else-if="slotEmblem(item, slot)">
              <strong>{{ slotEmblem(item, slot)!.name }}</strong>
            </template>
            <template v-else><em>未装备</em></template>
          </div>
        </div>

      </article>
    </div>

    <AppDialog v-model:open="detailOpen" :footer="null" variant="detail" :width="720" transition-name="stella-dialog"
             mask-transition-name="stella-mask" centered
             :title="detail ? `${detail.name} · Lv.${detail.level} · 突破 ${detail.advance}` : '角色详情'">
      <div v-if="detail" class="detail-modal">
        <h3>纹章</h3>
        <p v-if="!detail.emblems.length" class="muted">没有读到纹章，请先在游戏里打开「纹章」界面再读取。</p>
        <div v-for="emblem in detail.emblems" :key="`${emblem.slot}-${emblem.index}`"
             class="emblem" :class="{ equipped: emblem.active }">
          <EmblemThumbnail :emblem="emblem"/>
          <div class="emblem-content">
            <div class="emblem-head">
              <strong>
                {{ emblem.name }}
                <em v-if="emblem.active" class="equip-badge">装备中</em>
              </strong>
              <span>{{ emblem.typeName }} · 方案{{ emblem.preset }} · 强化 {{ upgradeTotal(emblem) }}</span>
            </div>
            <div v-if="emblem.skillAffixes.length || emblem.potentialAffixes.length" class="attrs affix-row">
              <span v-for="(affix, index) in emblem.skillAffixes" :key="'skill-' + index" class="affix">{{ affix.name }}</span>
              <span v-for="(affix, index) in emblem.potentialAffixes" :key="'potential-' + index" class="affix">{{ affix.name }}</span>
            </div>
            <div class="attrs">
              <span v-for="(attr, index) in emblem.attrs" :key="index">{{ attrText(attr) }}</span>
              <span v-if="!emblem.attrs.length && affixNames(emblem).length" class="affix">{{ affixNames(emblem).join(' / ') }}</span>
            </div>
          </div>
        </div>

        <h3>天赋节点</h3>
        <p class="muted">
          {{ detail.talent.nodes.length }} 个节点已激活<template v-if="detail.talent.fate.length">，命运天赋 {{ detail.talent.fate.length }} 层</template>
        </p>
        <div v-if="talentNames(detail).length" class="attrs">
          <span v-for="(name, index) in talentNames(detail).slice(0, 12)" :key="index"
                :title="detail.talent.descs[detail.talent.names.indexOf(name)] || ''">{{ name || `节点#${detail.talent.nodes[index]}` }}</span>
          <span v-if="talentNames(detail).length > 12" class="affix">… 还有 {{ talentNames(detail).length - 12 }} 个</span>
        </div>

        <template v-if="potentialGroups(detail).length">
          <h3>潜能</h3>
          <div v-for="group in potentialGroups(detail)" :key="group.key" class="potential-group">
            <small>{{ group.label }}</small>
            <div class="attrs"><span v-for="name in group.names" :key="name">{{ name }}</span></div>
          </div>
        </template>
      </div>
    </AppDialog>

    <AppDialog v-model:open="emblemOpen" :footer="null" variant="detail" :width="560" transition-name="stella-dialog"
             mask-transition-name="stella-mask" centered
             :title="emblemDetail ? `${emblemDetail.emblem.name} · ${emblemDetail.emblem.typeName}` : '纹章详情'">
      <div v-if="emblemDetail" class="detail-modal">
        <div class="emblem-detail-heading">
          <EmblemThumbnail :emblem="emblemDetail.emblem"/>
          <p class="muted">
            {{ emblemDetail.owner }} · 方案{{ emblemDetail.emblem.preset }} · 强化 {{ upgradeTotal(emblemDetail.emblem) }}
            <template v-if="emblemDetail.emblem.locked"> · 已锁定</template>
          </p>
        </div>
        <div v-if="emblemDetail.emblem.skillAffixes.length || emblemDetail.emblem.potentialAffixes.length" class="attrs affix-row">
          <span v-for="(affix, index) in emblemDetail.emblem.skillAffixes" :key="'skill-' + index" class="affix">{{ affix.name }}</span>
          <span v-for="(affix, index) in emblemDetail.emblem.potentialAffixes" :key="'potential-' + index" class="affix">{{ affix.name }}</span>
        </div>
        <div class="attrs">
          <span v-for="(attr, index) in emblemDetail.emblem.attrs" :key="index">{{ attrText(attr) }}</span>
          <span v-if="!emblemDetail.emblem.attrs.length && affixNames(emblemDetail.emblem).length" class="affix">
            {{ affixNames(emblemDetail.emblem).join(' / ') }}
          </span>
        </div>
      </div>
    </AppDialog>
  </section>
</template>

<style scoped>
.roster-meta{display:flex;align-items:center;gap:30px;padding:20px 24px;margin-bottom:22px;flex-wrap:wrap}
.meta-item{display:flex;align-items:baseline;gap:6px;color:var(--muted);font-size:11px}
.meta-item strong{font-size:23px;font-weight:620;color:var(--text);font-variant-numeric:tabular-nums}
.meta-item small{color:var(--muted)}
.meta-note{margin-left:auto;text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:5px;font-size:11px;color:var(--text);max-width:46%}
.meta-note .uid-line{font-size:12px;font-variant-numeric:tabular-nums}
.meta-note .uid-line strong{color:var(--primary);font-weight:600;margin-right:3px}
.meta-note small{color:var(--muted);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.roster-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.roster-card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px 15px;box-shadow:var(--shadow)}
.card-head{display:flex;align-items:center;gap:12px;cursor:pointer}
.avatar{width:46px;height:46px;border-radius:10px;object-fit:cover;background:var(--surface-2);flex-shrink:0}
.title{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px}
.title strong{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.title span{font-size:11px;color:var(--muted);font-variant-numeric:tabular-nums}
.favorite{color:#e3a94f;font-size:12px}
.chevron{font-size:11px;color:var(--primary);background:var(--primary-soft);border-radius:6px;padding:3px 8px;flex-shrink:0}
.skills{display:flex;flex-wrap:wrap;gap:6px;margin-top:13px}
.chip{font-size:11px;color:var(--muted);background:var(--surface-2);border-radius:6px;padding:3px 7px;font-variant-numeric:tabular-nums}
.chip b{color:var(--text);font-weight:600;margin-left:2px}
.talent{margin-top:13px}
.talent-head{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:5px}
.talent-head b{color:var(--text);font-variant-numeric:tabular-nums}
.bar{height:5px;border-radius:3px;background:var(--surface-2);overflow:hidden}
.bar i{display:block;height:100%;border-radius:3px;background:linear-gradient(90deg,var(--primary),#8ec9e6);transition:width .25s ease}
.slots{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:13px}
.slot{background:var(--surface-2);border-radius:8px;padding:7px 9px;display:flex;flex-direction:column;gap:3px;min-width:0}
.slot small{font-size:10px;color:var(--muted)}
.slot strong{font-size:11px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.slot em{font-size:11px;font-style:normal;color:var(--muted)}
.slot.clickable{cursor:pointer;transition:background .16s ease}
.slot.clickable:hover{background:var(--primary-soft)}
.detail-modal{max-height:70vh;overflow:auto;padding-right:4px}
.detail-modal h3{font-size:12px;margin:0 0 8px;color:var(--text)}
.detail-modal h3 + h3{margin-top:14px}
.emblem{display:flex;align-items:flex-start;gap:10px;padding:10px;border-radius:8px;background:var(--surface-2);margin-bottom:8px;border:1px solid transparent}
.emblem-content{flex:1;min-width:0}
.emblem-detail-heading{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.emblem-detail-heading p{margin:0;font-size:11px}
.emblem.equipped{border-color:var(--primary);background:var(--primary-soft)}
.equip-badge{font-style:normal;font-size:10px;color:#fff;background:var(--primary);border-radius:4px;padding:1px 5px;margin-left:6px;vertical-align:1px}
.emblem-head{display:flex;justify-content:space-between;gap:10px;font-size:11px;flex-wrap:wrap}
.emblem-head strong{font-size:12px}
.emblem-head span{color:var(--muted)}
.attrs{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.attrs span{font-size:11px;background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:2px 6px;font-variant-numeric:tabular-nums}
.attrs .affix{color:var(--muted)}
.attrs.affix-row span{color:var(--primary);border-color:var(--primary-soft);background:var(--primary-soft)}
.potential-group{margin-bottom:8px}
.potential-group small{display:block;font-size:10px;color:var(--muted);margin-bottom:4px}
@media(max-width:1150px){.roster-grid{grid-template-columns:repeat(auto-fill,minmax(290px,1fr))}.meta-note{margin-left:0;text-align:left}}
</style>
