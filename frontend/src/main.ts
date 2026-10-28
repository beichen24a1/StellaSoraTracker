import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import Antd from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import './style.css'
import './motion.css'
import App from './App.vue'
import OverviewView from './views/OverviewView.vue'
import RecordsView from './views/RecordsView.vue'
import AffinityView from './views/AffinityView.vue'
import SettingsView from './views/SettingsView.vue'
import UploadView from './views/UploadView.vue'
import HelpView from './views/HelpView.vue'
import CalendarView from './views/CalendarView.vue'
const router = createRouter({ history: createWebHashHistory(), routes: [
  { path: '/', component: OverviewView }, { path: '/records', component: RecordsView },
  { path: '/affinity', component: AffinityView },
  { path: '/calendar', component: CalendarView },
  { path: '/settings', component: SettingsView }, { path: '/upload', component: UploadView }, { path: '/help', component: HelpView },
] })
createApp(App).use(createPinia()).use(router).use(Antd).mount('#app')
