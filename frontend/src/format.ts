export function number(value: number | null | undefined) { return value == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value) }
export function date(value: number | undefined) { return value ? new Date(value * 1000).toLocaleDateString('zh-CN').replaceAll('/', '.') : '暂无记录' }
export function bytes(value = 0) { if (value < 1024) return `${value.toFixed(0)} B`; if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`; return `${(value / 1024 ** 2).toFixed(1)} MB` }
export function duration(value?: number | null) { if (value == null || !Number.isFinite(value)) return '计算中'; return value < 60 ? `${Math.ceil(value)} 秒` : `${Math.ceil(value / 60)} 分钟` }
export function avatar(itemId: number, kind: string) { return `app://assets/${kind === 'disc' ? 'discs' : 'travelers'}/${itemId}.png` }
