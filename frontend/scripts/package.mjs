import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { normalizeVersion } from './version.mjs'
const frontend=path.resolve(import.meta.dirname,'..')
const constants=fs.readFileSync(path.resolve(frontend,'../stellasora_toolkit/constants.py'),'utf8')
const version=/^APP_VERSION\s*=\s*["']([^"']+)["']/m.exec(constants)?.[1]
if(!version) throw new Error('APP_VERSION is missing')
// Recent Electron packages provide an explicit installer instead of postinstall.
// It is idempotent and checks the runtime version before downloading anything.
const runtime=spawnSync(process.execPath,[path.join(frontend,'node_modules/electron/install.js')],
  {cwd:frontend,stdio:'inherit',env:process.env})
if(runtime.error) throw runtime.error
if(runtime.status !== 0) process.exit(runtime.status || 1)
const result=spawnSync(process.execPath,[path.join(frontend,'node_modules/electron-builder/cli.js'),
  '--win','dir','--x64','--publish','never',`--config.extraMetadata.version=${normalizeVersion(version)}`],
  {cwd:frontend,stdio:'inherit',env:process.env})
if(result.error) throw result.error
process.exit(result.status || 0)
