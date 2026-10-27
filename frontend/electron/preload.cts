import { contextBridge, ipcRenderer } from 'electron'
contextBridge.exposeInMainWorld('stella', {
  request: (method: string, params: Record<string, unknown> = {}) => ipcRenderer.invoke('stella:request', method, params),
  onEvent: (callback: (event: unknown) => void) => {
    const handler = (_event: Electron.IpcRendererEvent, value: unknown) => callback(value)
    ipcRenderer.on('stella:event', handler)
    return () => ipcRenderer.removeListener('stella:event', handler)
  },
})
