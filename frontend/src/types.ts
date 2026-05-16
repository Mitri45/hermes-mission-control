export type InstanceFilter = 'all' | 'pc' | 'pi'
export type ActionInstance = 'pc' | 'pi'
export type DigestSource = 'arxiv' | 'web' | 'custom' | 'telegram'

export interface ServiceInfo {
  name: string
  status: string
  port?: number | null
  pid?: number | null
}

export interface TailscaleInfo {
  funnel: boolean
  hostname: string
  ip?: string | null
}

export interface SystemStatus {
  requested_instance: InstanceFilter
  resolved_instance: ActionInstance
  source_label: string
  cpu_temp?: number | null
  cpu_usage: number
  memory_used: number
  memory_total: number
  disk_used: number
  disk_total: number
  services: ServiceInfo[]
  tailscale: TailscaleInfo
  timestamp?: string
}

// ==================== Config & Memory ====================

export interface AgentConfig {
  model: string
  provider: string
  base_url: string
  personality: string
  max_turns: number
  linear_backend: string
}

export interface AgentConfigUpdate {
  model?: string
  provider?: string
  base_url?: string
  personality?: string
  max_turns?: number
  linear_backend?: string
}

export interface MemoryEntry {
  key: string
  value: string
  updated_at: string
}

export interface PersonalityInfo {
  current: string
  available: string[]
}

export interface MemoryResponse {
  entries: MemoryEntry[]
  personality: PersonalityInfo
}

// ==================== Hindsight Bank ====================

export type HindsightSource = 'all' | 'pc' | 'pi'

export interface HindsightFact {
  id: string
  content: string
  context: string
  timestamp?: string | null
  source_peer: 'pc' | 'pi' | 'unknown'
  entities: string[]
  metadata: Record<string, string>
  tags: string[]
  document_id?: string | null
  fact_type?: string | null
  created_at?: string | null
  updated_at?: string | null
  stale_reasons: string[]
  soft_deleted: boolean
}

export interface HindsightFactsResponse {
  items: HindsightFact[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface HindsightFactDetailResponse {
  fact: HindsightFact
  audit_log: Array<Record<string, unknown>>
}

export interface HindsightFactUpdateRequest {
  content: string
  context?: string | null
}

export interface HindsightBulkDeleteRequest {
  fact_ids: string[]
  soft_delete: boolean
}

export interface HindsightMutationResponse {
  success: boolean
  message: string
  affected_ids: string[]
  audit_id?: string | null
}

export interface HindsightBankStatsResponse {
  total_facts: number
  facts_per_context: Record<string, number>
  facts_per_source: Record<string, number>
  storage_estimate_bytes: number
  last_sync_timestamp?: string | null
  stale_candidates: number
}

export interface HindsightHealthResponse {
  backend: string
  ok: boolean
  bank_id: string
  base_url?: string | null
  error?: string | null
}

export interface HindsightStaleFactsResponse {
  items: HindsightFact[]
  total: number
}

export interface MemoryIngestHealthResponse {
  backend: string
  ok: boolean
  error?: string | null
  db_path?: string | null
}

// ==================== Digest Types ====================

export interface DigestEntry {
  id: string
  title: string
  summary: string
  content?: string | null
  source: DigestSource
  source_url?: string | null
  source_instance: ActionInstance
  tags: string[]
  ingested_at: string
  updated_at: string
  replicated_at?: string | null
  replication_seq?: number | null
  metadata: Record<string, unknown>
}

export interface DigestDayGroup {
  date: string
  entries: DigestEntry[]
  count: number
}

export interface DigestListResponse {
  entries: DigestEntry[]
  groups: DigestDayGroup[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface DigestDetailResponse {
  entry: DigestEntry
}

export interface DigestStatsResponse {
  total_entries: number
  by_source: Record<string, number>
  by_instance: Record<string, number>
  last_24h: number
  last_7d: number
  replication_lag_seconds?: number | null
}

export interface CronJob {
  id: string
  name: string
  schedule: string
  next_run?: string
  last_run?: string
  status: 'active' | 'paused' | 'running' | 'error' | string
  enabled: boolean
  target: string
  instance: 'pc' | 'pi' | 'both' | string
  last_result?: 'success' | 'failed' | 'triggered' | string
  runtime_seconds?: number | null
  failure_reason?: string | null
  failure_count: number
}

export interface CronResponse {
  jobs: CronJob[]
}

export interface CronJobUpdateRequest {
  name?: string
  schedule?: string
  enabled?: boolean
  target?: string
  instance?: 'pc' | 'pi' | 'both'
}

export interface ApiResponse {
  success: boolean
  message?: string
  data?: Record<string, unknown>
}

export interface AgentSession {
  id: string
  issue_id?: string
  issue_title?: string
  backend: string
  status: string
  started_at?: string
  worktree?: string
  platform?: string | null
  base_url?: string | null
  message_count?: number | null
  last_updated_at?: string | null
  source?: string
  summary?: string | null
  prompt?: string | null
}

export interface SessionsResponse {
  sessions: AgentSession[]
}

export interface HarnessStatus {
  webhook?: {
    status?: string
  }
}

export interface ChatResponse {
  response: string
  type: string
  session_id: string
  model?: string | null
  provider?: string | null
  base_url?: string | null
  message_count: number
}

export interface ChatMessage {
  role: string
  content?: string | null
  timestamp?: string | null
  tool_name?: string | null
}

export interface ChatSessionResponse {
  session_id: string
  model?: string | null
  provider?: string | null
  base_url?: string | null
  message_count: number
  messages: ChatMessage[]
}

export interface JobLogsResponse {
  success: boolean
  job_id: string
  logs: string[]
}

export type ProviderPanelStatus = 'active' | 'off-limits' | 'exhausted' | 'misconfigured' | 'unknown'

export interface ProviderFlowUsage {
  flow: string
  instance: ActionInstance
  model?: string | null
}

export interface ProviderStatusItem {
  provider: string
  name: string
  base_url?: string | null
  current_model?: string | null
  status: ProviderPanelStatus
  status_reason?: string | null
  recovery_eta_seconds?: number | null
  recovery_eta?: string | null
  primary_flows: ProviderFlowUsage[]
  last_error?: string | null
  key_source?: string | null
}

export interface ProviderStatusSummary {
  total: number
  active: number
  off_limits: number
  exhausted: number
  misconfigured: number
  unknown: number
}

export interface ProviderStatusResponse {
  instance: InstanceFilter
  generated_at: string
  providers: ProviderStatusItem[]
  summary: ProviderStatusSummary
}
