import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { mount, flushPromises } from '@vue/test-utils'
import Antd from 'ant-design-vue'
import { useAppStore } from '../../src/store'
import type { AppState } from '../../src/types'
import SettingsView from '../../src/views/SettingsView.vue'
import UpdateDialog from '../../src/components/UpdateDialog.vue'
import { bytes, duration, number } from '../../src/format'

let request: ReturnType<typeof vi.fn>
let wrappers: ReturnType<typeof mount>[]
function state(): AppState {
  return { protocolVersion:1,version:'1.3.0.bata1',busy:false,offline:false,packaged:true,
    preferences:{color_mode:'light',auto_upload:false,auto_update:true,pool_columns:null,update_channel:'beta'},
    accounts:[{key:'default',uid:'',name:'',label:'默认账号',groups:0}],activeAccount:'default',server:'cn',serverManual:false,
    servers:[{key:'cn',label:'国服'}],archivePath:'D:/exports/default.json',outputPath:'D:/exports',bindCommand:'',tasks:[],update:{status:'idle'},
    summary:{uid:'',pulls:0,five:0,rate:0,average:null,groups:0,categories:[],activity:[],firstTime:0,lastTime:0} }
}
beforeEach(() => {
  setActivePinia(createPinia()); wrappers=[]
  request=vi.fn().mockImplementation(async (method, params) => {
    if(method==='preferences.save')return {...useAppStore().state!.preferences,...params}
    return {ok:true}
  })
  window.stella={request,onEvent:()=>()=>{},importFiles:vi.fn()}
  useAppStore().state=state()
})
afterEach(() => { for(const wrapper of wrappers)wrapper.unmount(); document.body.innerHTML='' })
function component(value: any) { const wrapper=mount(value,{attachTo:document.body,global:{plugins:[Antd]}}); wrappers.push(wrapper); return wrapper }
async function click(text: string) { const button=Array.from(document.querySelectorAll('button')).find(value=>value.textContent?.replace(/\s/g,'')===text); expect(button).toBeTruthy(); button!.click(); await flushPromises() }

describe('appearance and update workflows',()=>{
  it('switches only two themes without losing unsaved UID input',async()=>{
    const view=component(SettingsView)
    const uid=view.find('input[aria-label="游戏 UID"]')
    await uid.setValue('100000123')
    await view.get('button[aria-label="黑色主题"]').trigger('click'); await flushPromises()
    expect(useAppStore().state!.preferences.color_mode).toBe('dark')
    expect((uid.element as HTMLInputElement).value).toBe('100000123')
    expect(view.text()).not.toContain('今日运势')
    expect(view.findAll('.theme-options>button')).toHaveLength(2)
  })
  it('shows release notes and downloads only after confirmation',async()=>{
    const store=useAppStore();store.updateOpen=true
    store.update={status:'available',update:{version:'9.0.0',url:'https://example.test/tool.zip',sha256:'0'.repeat(64),notes:'修复归档\n保留账号'}}
    component(UpdateDialog); await flushPromises()
    expect(document.body.textContent).toContain('修复归档')
    expect(request).not.toHaveBeenCalled()
    await click('下载更新')
    expect(request).toHaveBeenCalledWith('updates.download',{})
  })
  it('background download hides the window without cancelling the task',async()=>{
    const store=useAppStore();store.updateOpen=true
    store.update={status:'downloading',received:1024,total:2048,speed:512,eta:2}
    component(UpdateDialog); await flushPromises()
    expect(document.body.textContent).toContain('50.0%')
    expect(document.body.textContent).toContain('2 秒')
    await click('后台下载')
    expect(store.updateOpen).toBe(false)
    expect(request).not.toHaveBeenCalledWith('updates.cancel',{})
  })
  it('defers installation without deleting a verified package',async()=>{
    const store=useAppStore();store.updateOpen=true;store.update={status:'ready'}
    component(UpdateDialog); await flushPromises()
    await click('稍后安装')
    expect(store.updateOpen).toBe(false)
    expect(store.update.status).toBe('ready')
    expect(request).not.toHaveBeenCalled()
  })
  it('blocks installing while data is being saved',async()=>{
    const store=useAppStore();store.updateOpen=true;store.update={status:'ready'};store.state!.busy=true
    component(UpdateDialog); await flushPromises()
    const install=Array.from(document.querySelectorAll('button')).find(b=>b.textContent?.trim()==='立即安装并重启')!
    expect(install.disabled).toBe(true)
  })
  it('allows retrying failed downloads',async()=>{
    const store=useAppStore();store.updateOpen=true;store.update={status:'failed',error:'网络中断',update:{version:'9',url:'https://example.test/a.zip',sha256:'0'.repeat(64),notes:''}}
    component(UpdateDialog);await flushPromises();await click('重试')
    expect(request).toHaveBeenCalledWith('updates.download',{})
  })
  it('formats unknown size and ETA without invalid numbers',()=>{
    expect(number(null)).toBe('—');expect(bytes(1048576)).toBe('1.0 MB');expect(duration(null)).toBe('计算中')
  })
})
