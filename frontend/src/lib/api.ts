import type {
  AgentConfig,
  AgentConfigUpdate,
  ActionInstance,
  ChatSessionResponse,
  HindsightBankStatsResponse,
  HindsightBulkDeleteRequest,
  HindsightFactDetailResponse,
  HindsightFactsResponse,
  HindsightHealthResponse,
  HindsightFactUpdateRequest,
  HindsightMutationResponse,
  HindsightSource,
  HindsightStaleFactsResponse,
  MemoryResponse,
  CronResponse,
  CronJobUpdateRequest,
  ApiResponse,
  HarnessStatus,
  InstanceFilter,
  JobLogsResponse,
  MemoryIngestHealthResponse,
  SessionsResponse,
  ChatResponse,
  SystemStatus,
  ProviderStatusResponse,
  DigestListResponse,
  DigestDetailResponse,
  DigestStatsResponse,
  DigestSource,
} from '../types'

const DASHBOARD_TOKEN_STORAGE_KEY = 'hermes.dashboardBearerToken'

export function setDashboardBearerToken(token: string): void {
  if (typeof window === 'undefined') return
  const cleaned = token.trim()
  if (cleaned) {
    window.localStorage.setItem(DASHBOARD_TOKEN_STORAGE_KEY, cleaned)
  }
}

export function clearDashboardBearerToken(): void {
  if (typeof window === 'undefined') return
  window.localStorage.removeItem(DASHBOARD_TOKEN_STORAGE_KEY)
}

function getDashboardBearerToken(): string {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(DASHBOARD_TOKEN_STORAGE_KEY)?.trim() ?? ''
}

function encodeTokenForSubprotocol(token: string): string {
  const utf8 = new TextEncoder().encode(token)
  let binary = ''
  for (const byte of utf8) {
    binary += String.fromCharCode(byte)
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

export function buildOperationsStreamUrl(): string {
  if (typeof window === 'undefined') return ''
  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return new URL('/api/operations/stream', `${wsProtocol}//${window.location.host}`).toString()
}

export function buildOperationsStreamProtocols(): string[] {
  const token = getDashboardBearerToken()
  if (!token) return ['hermes-ops.v1']
  const encodedToken = encodeTokenForSubprotocol(token)
  return ['hermes-ops.v1', `hermes-auth.${encodedToken}`]
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const token = getDashboardBearerToken()
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    let detail = ''
    try {
      const errorBody = (await response.json()) as { detail?: string }
      detail = errorBody.detail ? ` - ${errorBody.detail}` : ''
    } catch {
      detail = ''
    }
    throw new Error(`API ${path} failed: ${response.status}${detail}`)
  }

  return (await response.json()) as T
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  })
}

async function patch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PATCH',
    body: body ? JSON.stringify(body) : undefined,
  })
}

async function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  })
}

async function del<T>(path: string): Promise<T> {
  return request<T>(path, {
    method: 'DELETE',
  })
}

export const api = {
  // System status
  getSystemStatus: (instance: InstanceFilter = 'all') =>
    request<SystemStatus>(`/status?instance=${encodeURIComponent(instance)}`),

  // Cron jobs
  getCron: (instance: InstanceFilter = 'all') =>
    request<CronResponse>(`/cron?instance=${encodeURIComponent(instance)}`),

  pauseJob: (jobId: string, instance: ActionInstance) =>
    post<ApiResponse>(`/cron/${jobId}/pause?instance=${encodeURIComponent(instance)}`),

  resumeJob: (jobId: string, instance: ActionInstance) =>
    post<ApiResponse>(`/cron/${jobId}/resume?instance=${encodeURIComponent(instance)}`),

  runJob: (jobId: string, instance: ActionInstance) =>
    post<ApiResponse>(`/cron/${jobId}/run?instance=${encodeURIComponent(instance)}`),

  retryJob: (jobId: string, instance: ActionInstance) =>
    post<ApiResponse>(`/cron/${jobId}/retry?instance=${encodeURIComponent(instance)}`),

  updateJob: (jobId: string, data: CronJobUpdateRequest) =>
    patch<ApiResponse>(`/cron/${jobId}`, data),

  getJobLogs: (jobId: string, lines: number = 50) =>
    request<JobLogsResponse>(`/cron/${jobId}/logs?lines=${lines}`),

  // Sessions
  getSessions: () => request<SessionsResponse>('/harness/sessions'),
  sendChat: (message: string, sessionId?: string, stream: boolean = false) =>
    post<ChatResponse>('/chat', { message, stream, session_id: sessionId }),
  getChatSession: (sessionId: string) =>
    request<ChatSessionResponse>(`/chat/session/${encodeURIComponent(sessionId)}`),

  // Harness
  getHarnessStatus: () => request<HarnessStatus>('/harness/status'),

  // Config + memory
  getConfig: () => request<AgentConfig>('/config'),
  updateConfig: (data: AgentConfigUpdate) => post<AgentConfig>('/config', data),
  getMemory: () => request<MemoryResponse>('/memory'),

  // Digest
  getDigests: (
    instance: InstanceFilter = 'all',
    source?: DigestSource,
    page: number = 1,
    pageSize: number = 50,
    days?: number,
  ) => {
    const params = new URLSearchParams()
    params.set('instance', instance)
    if (source) params.set('source', source)
    params.set('page', String(page))
    params.set('page_size', String(pageSize))
    if (days) params.set('days', String(days))
    return request<DigestListResponse>(`/digest?${params.toString()}`)
  },

  getDigest: (entryId: string) =>
    request<DigestDetailResponse>(`/digest/${encodeURIComponent(entryId)}`),

  getDigestStats: (instance: InstanceFilter = 'all') =>
    request<DigestStatsResponse>(`/digest/stats?instance=${encodeURIComponent(instance)}`),

  // Provider visibility
  getProviderStatus: (instance: InstanceFilter = 'all') =>
    request<ProviderStatusResponse>(`/v1/provider-status?instance=${encodeURIComponent(instance)}`),

  getMemoryIngestHealth: () =>
    request<MemoryIngestHealthResponse>('/memory/ingest/health'),

  // Hindsight bank
  getHindsightHealth: () => request<HindsightHealthResponse>('/hindsight/bank/health'),

  getHindsightStats: (source: HindsightSource = 'all') =>
    request<HindsightBankStatsResponse>(`/hindsight/bank/stats?source=${encodeURIComponent(source)}`),

  getHindsightFacts: (params: {
    q?: string
    context?: string
    source?: HindsightSource
    from_date?: string
    to_date?: string
    stale_only?: boolean
    sort?: 'newest' | 'oldest'
    limit?: number
    offset?: number
  } = {}) => {
    const search = new URLSearchParams()
    if (params.q) search.set('q', params.q)
    if (params.context) search.set('context', params.context)
    search.set('source', params.source ?? 'all')
    if (params.from_date) search.set('from_date', params.from_date)
    if (params.to_date) search.set('to_date', params.to_date)
    if (params.stale_only) search.set('stale_only', 'true')
    search.set('sort', params.sort ?? 'newest')
    search.set('limit', String(params.limit ?? 50))
    search.set('offset', String(params.offset ?? 0))
    return request<HindsightFactsResponse>(`/hindsight/bank/facts?${search.toString()}`)
  },

  searchHindsightFacts: (params: {
    q: string
    source?: HindsightSource
    context?: string
    from_date?: string
    to_date?: string
    sort?: 'newest' | 'oldest'
    limit?: number
    offset?: number
  }) => {
    const search = new URLSearchParams()
    search.set('q', params.q)
    search.set('source', params.source ?? 'all')
    if (params.context) search.set('context', params.context)
    if (params.from_date) search.set('from_date', params.from_date)
    if (params.to_date) search.set('to_date', params.to_date)
    search.set('sort', params.sort ?? 'newest')
    search.set('limit', String(params.limit ?? 50))
    search.set('offset', String(params.offset ?? 0))
    return request<HindsightFactsResponse>(`/hindsight/bank/search?${search.toString()}`)
  },

  getHindsightFact: (factId: string) =>
    request<HindsightFactDetailResponse>(`/hindsight/bank/facts/${encodeURIComponent(factId)}`),

  updateHindsightFact: (factId: string, data: HindsightFactUpdateRequest) =>
    put<HindsightFactDetailResponse>(`/hindsight/bank/facts/${encodeURIComponent(factId)}`, data),

  deleteHindsightFact: (factId: string, softDelete: boolean = true) =>
    del<HindsightMutationResponse>(
      `/hindsight/bank/facts/${encodeURIComponent(factId)}?soft_delete=${softDelete ? 'true' : 'false'}`,
    ),

  bulkDeleteHindsightFacts: (data: HindsightBulkDeleteRequest) =>
    post<HindsightMutationResponse>('/hindsight/bank/facts/bulk-delete', data),

  getHindsightStaleFacts: (source: HindsightSource = 'all') =>
    request<HindsightStaleFactsResponse>(`/hindsight/bank/stale?source=${encodeURIComponent(source)}`),
}
