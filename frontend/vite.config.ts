import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({ plugins: [vue(), { name: 'development-csp', apply: 'serve', transformIndexHtml: html => html.replace(/<meta http-equiv="Content-Security-Policy"[^>]*>/, '') }], base: './', build: { target: 'es2022' } })
