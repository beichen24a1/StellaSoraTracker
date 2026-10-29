import { expect, it } from 'vitest'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { recoveryHtml } = require('../../dist-electron/recovery.cjs') as { recoveryHtml(details: string, dark: boolean): string }

it('renders untrusted error details as text with a nonce-only script and no external resource permissions', () => {
  const payload = '</pre><script>window.bad=true</script><img src=x onerror=alert(1)>'
  const html = recoveryHtml(payload, true)
  const parsed = new DOMParser().parseFromString(html, 'text/html')
  expect(parsed.querySelector('pre')?.textContent).toBe(payload)
  expect(parsed.querySelectorAll('script')).toHaveLength(1)
  expect(parsed.querySelector('img')).toBeNull()
  const policy = parsed.querySelector('meta[http-equiv="Content-Security-Policy"]')!.getAttribute('content')!
  expect(policy).toContain("default-src 'none'")
  expect(policy).toContain("script-src 'nonce-")
  expect(policy).not.toContain("script-src 'unsafe-inline'")
  expect(parsed.documentElement.style.colorScheme).toBe('dark')
})
