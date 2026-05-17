import type { FleetStatusResponse, HindsightBankStatsResponse, HindsightFactsResponse, HindsightHealthResponse, HindsightSource, HindsightStaleFactsResponse, MissionControlHealth, MissionControlSummary, ProviderStatusResponse, MemoryIngestHealthResponse, MemoryIngestMetricsResponse, DeadLetterResponse, DigestListResponse, DigestStatsResponse, HarnessStatusResponse, SessionsResponse, WorkersResponse, OperationsRecentResponse } from './types'

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
  fleetStatus: () => mcFetch<FleetStatusResponse>('/fleet/status'),
  hindsightHealth: () => mcFetch<HindsightHealthResponse>('/hindsight/health'),
  hindsightStats: (source: HindsightSource = 'all') => mcFetch<HindsightBankStatsResponse>(`/hindsight/stats?source=${encodeURIComponent(source)}`),
  hindsightFacts: (params: { q?: string; context?: string; source?: HindsightSource; stale_only?: boolean; sort?: 'newest' | 'oldest'; limit?: number; offset?: number } = {}) => {
    const search = new URLSearchParams()
    if (params.q) search.set('q', params.q)
    if (params.context) search.set('context', params.context)
    search.set('source', params.source ?? 'all')
    if (params.stale_only) search.set('stale_only', 'true')
    search.set('sort', params.sort ?? 'newest')
    search.set('limit', String(params.limit ?? 25))
    search.set('offset', String(params.offset ?? 0))
    return mcFetch<HindsightFactsResponse>(`/hindsight/facts?${search.toString()}`)
  },
  hindsightStale: (source: HindsightSource = 'all') => mcFetch<HindsightStaleFactsResponse>(`/hindsight/stale?source=${encodeURIComponent(source)}`),
  providerStatus: () => mcFetch<ProviderStatusResponse>('/providers/status'),
  memoryIngestHealth: () => mcFetch<MemoryIngestHealthResponse>('/memory-ingest/health'),
  memoryIngestMetrics: () => mcFetch<MemoryIngestMetricsResponse>('/memory-ingest/metrics'),
  memoryIngestDeadLetters: () => mcFetch<DeadLetterResponse>('/memory-ingest/dead-letter?limit=8'),
  digestStats: () => mcFetch<DigestStatsResponse>('/digest/stats'),
  digestList: () => mcFetch<DigestListResponse>('/digest?page=1&page_size=8&days=30'),
  harnessStatus: () => mcFetch<HarnessStatusResponse>('/harness/status'),
  harnessSessions: () => mcFetch<SessionsResponse>('/harness/sessions'),
  harnessWorkers: () => mcFetch<WorkersResponse>('/harness/workers'),
  operationsRecent: () => mcFetch<OperationsRecentResponse>('/operations/recent?limit=20'),
}

