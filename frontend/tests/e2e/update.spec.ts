import { test, expect, _electron as electron } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
const frontend=path.resolve(import.meta.dirname,'../..')
test('update notes, progress, background, retry and later-install recovery across restart',async()=>{
  const base=path.resolve(frontend,'../build/electron-e2e');fs.mkdirSync(base,{recursive:true})
  const root=fs.mkdtempSync(path.join(base,'updates-'));const output=path.join(root,'exports');fs.mkdirSync(output)
  fs.writeFileSync(path.join(output,'ui_settings.json'),JSON.stringify({auto_update:false,color_mode:'dark'}))
  const env={...process.env,STELLA_OUTPUT:output,STELLA_PROFILE:path.join(root,'profile'),STELLA_E2E_UPDATES:'1',PYTHONPATH:path.join(frontend,'tests/fixtures')}
  delete env.ELECTRON_RUN_AS_NODE;delete env.NODE_OPTIONS;delete env.STELLA_OFFLINE
  const launch=()=>electron.launch({executablePath:path.join(frontend,'node_modules/electron/dist/electron.exe'),args:['--no-sandbox','.'],cwd:frontend,env})
  let desktop=await launch()
  try{
    const page=await desktop.firstWindow()
    await page.getByRole('link',{name:'数据与设置',exact:true}).click()
    await page.getByRole('button',{name:'检查更新',exact:true}).click()
    await expect(page.locator('.release-notes')).toContainText('改进归档保护')
    expect(await page.evaluate(()=>Boolean((window as any).bad))).toBe(false)
    await page.screenshot({path:path.join(base,'update-notes-dark.png')})
    await page.getByRole('button',{name:'下载更新',exact:true}).click()
    await expect(page.locator('.download-metrics')).toBeVisible()
    await page.getByRole('button',{name:'后台下载',exact:true}).click()
    await expect(page.locator('.update-modal')).not.toBeVisible()
    await expect(page.getByRole('button',{name:/重\s*试/,exact:true})).toBeVisible({timeout:10000})
    await page.getByRole('button',{name:/重\s*试/,exact:true}).click()
    await expect(page.locator('.download-metrics')).toBeVisible()
    await page.screenshot({path:path.join(base,'update-progress-dark.png')})
    await expect(page.getByText('下载完成，文件校验通过',{exact:true})).toBeVisible({timeout:10000})
    await page.getByRole('button',{name:'稍后安装',exact:true}).click()
    await expect(page.locator('.update-modal')).not.toBeVisible()
    expect(fs.existsSync(path.join(output,'updates/ready.json'))).toBe(true)
    await desktop.close();desktop=await launch()
    const second=await desktop.firstWindow()
    await expect(second.getByText('下载完成，文件校验通过',{exact:true})).toBeVisible()
    await second.screenshot({path:path.join(base,'update-ready-dark.png')})
  }finally{await desktop.close()}
})
