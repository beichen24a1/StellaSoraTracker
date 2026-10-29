import { contextBridge, ipcRenderer } from 'electron'
contextBridge.exposeInMainWorld('stellaRecovery', { perform: (action: string) => ipcRenderer.invoke('stella:recovery', action),
  onStatus: (callback: (message: string) => void) => { ipcRenderer.on('stella:recovery-status', (_event, message) => callback(message)) } })
