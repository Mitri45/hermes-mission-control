import type { MissionControlHealth, MissionControlSummary } from './types'

const API_PREFIX = '/api/plugins/mission-control'

function basePath(): string {
  const raw = window.__HERMES_BASE_PATH__ || ''
  if (!raw) return ''
  return raw.startsWith('/') ? raw.replace(/\/+$/, '') : `/${raw.replace(/\/+$/, '')}`
}

export async function mcFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  const token = window.__HERMES_SESSION_TOKEN__
  if (token && !headers.has('X-Hermes-Session-Token')) {
    headers.set('X-Hermes-Session-Token', token)
  }
  const response = await fetch(`${basePath()}${API_PREFIX}${path}`, { ...init, headers })
  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText)
    throw new Error(`${response.status}: ${text}`)
  }
  return response.json() as Promise<T>
}

export function missionControlWsUrl(path: string): string {
  const token = encodeURIComponent(window.__HERMES_SESSION_TOKEN__ || '')
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const prefix = basePath()
  return `${scheme}//${window.location.host}${prefix}${API_PREFIX}${path}?token=${token}`
}

export const missionControlApi = {
  health: () => mcFetch<MissionControlHealth>('/health'),
  summary: () => mcFetch<MissionControlSummary>('/summary'),
}
