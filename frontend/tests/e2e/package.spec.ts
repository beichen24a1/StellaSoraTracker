import { test, expect, _electron as electron } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
const frontend=path.resolve(import.meta.dirname,'../..')
test('extracted package uses frozen Python core without Python or Node on PATH',async()=>{
  test.skip(!process.env.STELLA_PACKAGED_EXE,'Run after local ZIP preparation')
  const executable=process.env.STELLA_PACKAGED_EXE!
  const root=path.dirname(executable)
  const fixture=fs.mkdtempSync(path.join(path.resolve(frontend,'../build'),'packaged-state-'))
  const output=path.join(fixture,'中文 数据');fs.mkdirSync(output)
  fs.writeFileSync(path.join(output,'100000001.json'),JSON.stringify({version:1,uid:'100000001',categories:{'6':[{Gid:1001,Time:1792700000,Ids:[162,103]}]}}))
  const env={...process.env,PATH:path.join(process.env.SystemRoot!,'System32'),STELLA_PROFILE:path.join(fixture,'profile'),STELLA_OUTPUT:output,STELLA_OFFLINE:'1'}
  delete env.PYTHONPATH;delete env.STELLA_E2E_UPDATES;delete env.ELECTRON_RUN_AS_NODE;delete env.NODE_OPTIONS
  const desktop=await electron.launch({executablePath:executable,args:['--no-sandbox'],cwd:root,env})
  try{
    const page=await desktop.firstWindow()
    await page.getByRole('link',{name:'招募总览',exact:true}).click()
    await expect(page.locator('.metric-card').first()).toContainText('2')
    const state=await page.evaluate(()=>window.stella.request('app.state'))
    expect(state.packaged).toBe(true);expect(state.summary.pulls).toBe(2)
    const displayVersion=/^APP_VERSION\s*=\s*["']([^"']+)["']/m.exec(fs.readFileSync(path.resolve(frontend,'../stellasora_toolkit/constants.py'),'utf8'))![1]
    expect(state.version).toBe(displayVersion)
    expect(await desktop.evaluate(({app})=>app.getVersion())).toBe(JSON.parse(fs.readFileSync(path.join(frontend,'package.json'),'utf8')).version)
    expect(await desktop.evaluate(({app})=>app.isPackaged)).toBe(true)
    expect(await desktop.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences().contextIsolation)).toBe(true)
    for(const [name,heading] of [['招募记录','招募记录'],['数据与设置','数据与设置'],['上传与分享','上传与分享'],['使用说明','使用说明与风险提示']]){
      await page.getByRole('link',{name,exact:true}).click();await expect(page.getByRole('heading',{name:heading,exact:true})).toBeVisible()
    }
    await page.screenshot({path:path.resolve(frontend,'../build/electron-e2e/packaged-help.png')})
    await page.getByRole('link',{name:'数据与设置',exact:true}).click()
    await page.getByRole('button',{name:'创建备份',exact:true}).click()
    await expect.poll(()=>fs.existsSync(path.join(output,'backups')) && fs.readdirSync(path.join(output,'backups')).length).toBe(1)
    await expect(page.evaluate(()=>window.stella.request('shell.execute',{command:'invalid'}))).rejects.toThrow()
    fs.writeFileSync(path.join(fixture,'passed.json'),JSON.stringify({packaged:true,noPythonOnPath:true,pulls:state.summary.pulls}))
  }finally{await desktop.close()}
})
