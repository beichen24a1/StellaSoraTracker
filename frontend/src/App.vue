<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { theme } from 'ant-design-vue'
import { AppstoreOutlined, ProfileOutlined, SettingOutlined, CloudUploadOutlined, QuestionCircleOutlined, ImportOutlined, ReloadOutlined, HistoryOutlined, CheckCircleFilled, HeartOutlined, IdcardOutlined, CalendarOutlined, HomeOutlined } from '@ant-design/icons-vue'
import { useAppStore } from './store'
import TasksDrawer from './components/TasksDrawer.vue'
import UpdateDialog from './components/UpdateDialog.vue'
const store = useAppStore()
const route = useRoute()
const navigation = [
  { to: '/', title: '主页', icon: HomeOutlined },
  { to: '/overview', title: '招募总览', icon: AppstoreOutlined }, { to: '/records', title: '招募记录', icon: ProfileOutlined },
  { to: '/affinity', title: '好感度', icon: HeartOutlined },
  { to: '/roster', title: '角色', icon: IdcardOutlined },
  { to: '/calendar', title: '活动日历', icon: CalendarOutlined },
  { to: '/settings', title: '数据与设置', icon: SettingOutlined }, { to: '/upload', title: '上传与分享', icon: CloudUploadOutlined },
  { to: '/help', title: '使用说明', icon: QuestionCircleOutlined },
]
const config = computed(() => ({ algorithm: store.colorMode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
  token: { colorPrimary: store.colorMode === 'dark' ? '#6aaed6' : '#23769a',
    colorBgContainer: store.colorMode === 'dark' ? '#1a222d' : '#ffffff',
    colorBgElevated: store.colorMode === 'dark' ? '#202b38' : '#ffffff',
    colorText: store.colorMode === 'dark' ? '#e4ecf5' : '#243b4d',
    colorTextSecondary: store.colorMode === 'dark' ? '#96a8ba' : '#7890a2',
    colorBorder: store.colorMode === 'dark' ? '#303e4e' : '#dfe9f0',
    motion: true, motionDurationFast: '0.14s', motionDurationMid: '0.22s', motionDurationSlow: '0.3s',
    borderRadius: 9, fontFamily: '"Segoe UI", "Microsoft YaHei UI", sans-serif' } }))
onMounted(() => void store.initialize())
onUnmounted(() => store.dispose())
</script>

<template>
  <a-config-provider :theme="config">
    <div class="desktop">
      <aside class="sidebar">
        <div class="brand"><img :src="'app://assets/app_icon.png'" alt="星塔旅人"><div><strong>STELLA SORA</strong><small>星塔旅人 · 招募档案</small></div></div>
        <div class="nav-caption">我的档案</div>
        <nav aria-label="全局导航" :style="{ '--nav-index': Math.max(0, navigation.findIndex(item => item.to === route.path)) }"><router-link v-for="item in navigation" :key="item.to" :to="item.to" :class="{ selected: route.path === item.to }"><component :is="item.icon" aria-hidden="true"/><span>{{ item.title }}</span></router-link></nav>
        <div class="sidebar-note"><strong>记录留在你身边</strong><span>历史归档 · 独立账号 · 支持备份</span></div>
        <small class="sidebar-foot">非官方工具 · Windows</small>
      </aside>
      <div class="main-shell">
        <header class="topbar"><div><strong>招募记录工具</strong><div class="topbar-sub">{{ store.state?.servers.find(s => s.key === store.state?.server)?.label || '正在连接' }} · 本地归档与卡池统计</div></div>
          <div class="top-actions"><a-button class="import-button" :disabled="store.busy" @click="store.importFiles()"><ImportOutlined aria-hidden="true"/> 导入文件</a-button><a-button type="primary" :loading="store.busy" @click="store.capture()"><ReloadOutlined v-if="!store.busy"/>抓取抽卡记录</a-button></div>
        </header>
        <a-alert v-if="store.error" type="error" show-icon :message="store.error" class="connection-error"><template #action><a-button size="small" @click="store.invoke('engine.reconnect').then(() => store.refresh())">重新连接</a-button></template></a-alert>
        <main class="page-area"><a-spin :spinning="store.loading"><router-view v-slot="{ Component, route: pageRoute }"><Transition name="page" mode="out-in" appear><component :is="Component" :key="pageRoute.path"/></Transition></router-view></a-spin></main>
        <footer class="statusbar"><button class="task-button" @click="store.taskDrawer = true"><HistoryOutlined aria-hidden="true"/><span>{{ store.activeTask ? store.activeTask.label+'…' : store.lastOperation }}</span><span v-if="store.activeTask" class="running-dot"></span></button><div class="status-right"><CheckCircleFilled aria-hidden="true"/> {{ store.state?.offline ? '离线验收' : '本地数据' }}<span>v{{ store.state?.version || '—' }}</span></div></footer>
      </div>
      <TasksDrawer/>
      <UpdateDialog/>
      <a-modal v-model:open="store.processDialog" transition-name="stella-dialog" mask-transition-name="stella-mask" title="选择游戏客户端" ok-text="开始读取" cancel-text="取消" @ok="store.startProcess()">
        <p class="muted">请选择本次读取的具体实例。</p>
        <a-radio-group v-model:value="store.selectedPid" class="process-list"><a-radio v-for="process in store.processes" :key="process.pid" :value="process.pid"><strong>{{ process.name }} · PID {{ process.pid }}</strong><small>{{ process.path || '路径不可用' }}</small></a-radio></a-radio-group>
      </a-modal>
    </div>
  </a-config-provider>
</template>
