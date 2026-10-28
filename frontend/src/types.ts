export interface Preferences { color_mode: 'light' | 'dark'; auto_upload: boolean; auto_update: boolean; pool_columns: 1 | 2 | null; update_channel: 'stable' | 'beta' }
export interface Account { key: string; uid: string; name: string; label: string; groups: number }
export interface Category { key: string; name: string; pulls: number; five: number; pity: number; limit: number; average: number | null }
export interface Summary { uid: string; pulls: number; five: number; rate: number; average: number | null; groups: number; categories: Category[]; activity: { gid: number; name: string; pulls: number; five_stars: number }[]; firstTime: number; lastTime: number }
export interface Task { id: string; label: string; state: 'running'|'succeeded'|'failed'|'cancelled'; logs: { time: string; message: string }[]; exclusive: boolean; error?: string; startedAt: string }
export interface Update { version: string; url: string; sha256: string; notes: string }
export interface UpdateState { status: string; update?: Update; automatic?: boolean; channel?: string; received?: number; total?: number; speed?: number; eta?: number | null; error?: string; stage?: string }
export interface AppState { protocolVersion: number; version: string; busy: boolean; offline: boolean; preferences: Preferences; accounts: Account[]; activeAccount: string; server: string; serverManual: boolean; servers: {key: string; label: string}[]; archivePath: string; outputPath: string; summary: Summary; tasks: Task[]; update: UpdateState; bindCommand: string; packaged: boolean }
export interface RecordRow { key: string; name: string; kind: string; itemId: number; time: number; five: boolean; poolName: string; result: string; gid: number; interval?: number | null }
export interface Pull { itemId: number; name: string; kind: string; time: number; interval: number | null; reward: boolean; result: string }
export interface Pool { gid: number; name: string; category: string; pulls: number; five: number; activity: boolean; start: string; end: string; lastTime: number; well: boolean; entries: Pull[]; entriesTotal?: number }
export interface QueryResult { items: (RecordRow | Pool)[]; total: number; page: number; pageSize: number }
export interface EngineEvent { type: 'event'; name: string; payload: any }
export interface ImportFile { token: string; name: string }
export interface AffinityEntry { id: number; name: string; level: number; exp: number; need: number; ratio: number; favorite: boolean }
export interface RosterEmblemAttr { attrId: number; value: number; cfgValue: number; name: string }
export interface RosterSkillAffix { typeId: number; id: number; level: number; name: string }
export interface RosterEmblem { slot: number; slotName: string; index: number; preset: number; active: boolean; name: string; type: number; typeName: string; gemId: number; generateId: number; refreshId: number; icon: string; desc: string; locked: boolean; upgrades: number[]; alterUpgrades: number[]; affixes: number[]; alterAffixes: number[]; skillAffixes: RosterSkillAffix[]; potentialAffixes: RosterSkillAffix[]; affixNames: string[]; attrs: RosterEmblemAttr[] }
export interface RosterTalent { active: number; max: number; nodes: number[]; names: string[]; descs: string[]; fate: number[] }
export interface RosterSlot { slot: number; name: string; unlockLevel: number }
export interface RosterCharacter { id: number; name: string; level: number; advance: number; favorite: boolean; skills: number[]; talent: RosterTalent; emblems: RosterEmblem[]; slots: RosterSlot[]; potentials: Record<string, string[]> }
export interface CalendarEntry { id: number; name: string; title: string; kind: 'version' | 'event' | 'permanent' | 'recruit'; startAt: number; endAt: number; startApproximate: boolean; description: string; cover: string; url: string }
export interface CalendarSnapshot { items: CalendarEntry[]; updatedAt: number; loading: boolean; stale: boolean; error: string; offline: boolean; source: string; sourceUrl: string }
export interface DesktopAPI { request<T=any>(method: string, params?: Record<string, unknown>): Promise<T>; onEvent(callback: (event: EngineEvent) => void): () => void }
declare global { interface Window { stella: DesktopAPI } }
