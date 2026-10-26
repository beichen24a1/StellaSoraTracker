import { expect,it } from 'vitest'
// @ts-expect-error Build helper is intentionally plain Node ESM.
import { normalizeVersion } from '../../scripts/version.mjs'
it('uses the shared display version for Electron metadata without renaming releases',()=>{
  expect(normalizeVersion('1.3.0.bata1')).toBe('1.3.0-beta.1')
  expect(normalizeVersion('1.3.0.bata2')).toBe('1.3.0-beta.2')
  expect(normalizeVersion('1.3.1')).toBe('1.3.1')
  expect(()=>normalizeVersion('latest')).toThrow()
})
