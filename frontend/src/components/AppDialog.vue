<script setup lang="ts">
import { computed, useAttrs } from 'vue'
import { ExclamationCircleOutlined, InfoCircleOutlined, FormOutlined, CloudDownloadOutlined, IdcardOutlined, CheckCircleOutlined } from '@ant-design/icons-vue'
defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ title: string; subtitle?: string; variant?: 'info'|'danger'|'form'|'update'|'detail'|'success' }>(), { variant: 'info', subtitle: '' })
const attrs = useAttrs()
const icon = computed(() => ({ info: InfoCircleOutlined, danger: ExclamationCircleOutlined, form: FormOutlined,
  update: CloudDownloadOutlined, detail: IdcardOutlined, success: CheckCircleOutlined }[props.variant]))
</script>
<template>
  <a-modal v-bind="attrs" :width="attrs.width || 560" :centered="attrs.centered ?? true" :mask-closable="attrs.maskClosable ?? false" transition-name="stella-dialog" mask-transition-name="stella-mask" :class="['stella-dialog', attrs.class]">
    <template #title><div class="stella-dialog-heading" :data-variant="variant"><div class="stella-dialog-mark"><component :is="icon" aria-hidden="true"/></div><div><small aria-hidden="true">STELLA SORA</small><h2>{{ title }}</h2><p v-if="subtitle">{{ subtitle }}</p></div></div></template>
    <template v-for="(_, name) in $slots" :key="name" #[name]="slotProps"><slot :name="name" v-bind="slotProps || {}"/></template>
  </a-modal>
</template>
