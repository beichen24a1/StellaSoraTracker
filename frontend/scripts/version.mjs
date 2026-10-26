export function normalizeVersion(value) {
  const parts=value.trim().replace(/^v/i,'').split('+')
  const match=/^(\d+)\.(\d+)\.(\d+)(?:[.-]?(bata|beta|b|alpha|a|rc)[.-]?(\d+))?$/i.exec(parts[0])
  if(!match || parts.length>2 || (parts[1] && !/^[a-zA-Z0-9.-]+$/.test(parts[1]))) throw new Error('APP_VERSION is not a supported release version')
  const stage=match[4]?.toLowerCase()
  const suffix=stage ? `-${({bata:'beta',b:'beta',a:'alpha'})[stage] || stage}.${match[5]}` : ''
  return `${match[1]}.${match[2]}.${match[3]}${suffix}${parts[1] ? '+'+parts[1] : ''}`
}
