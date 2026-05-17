export interface MissionControlHealth {
  status: string
  plugin: string
  version: string
}

export interface MissionControlSection {
  id: string
  label: string
  status: string
}

export interface MissionControlSummary {
  plugin: string
  version: string
  status: string
  sections: MissionControlSection[]
}

export interface ServiceInfo {
  name: string
  status: string
  port?: number | null
  pid?: number | null
}

export interface TailscaleInfo {
  funnel?: boolean
  hostname?: string
  ip?: string | null
  running?: boolean
}

export interface SystemStatus {
  requested_instance: 'all' | 'pc' | 'pi'
  resolved_instance: 'pc' | 'pi'
  source_label: string
  cpu_temp?: number | null
  cpu_usage: number
  memory_used: number
  memory_total: number
  disk_used: number
  disk_total: number
  services: ServiceInfo[]
  tailscale: TailscaleInfo
  timestamp: string
}

export interface InstanceStatusEnvelope {
  ok: boolean
  status: SystemStatus | null
  error: string | null
}

export interface FleetStatusResponse {
  generated_at: string
  instances: {
    pc: InstanceStatusEnvelope
    pi: InstanceStatusEnvelope
  }
}


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
  upstream_total?: number | null
  limit: number
  offset: number
  has_more: boolean
}

export interface HindsightStaleFactsResponse {
  items: HindsightFact[]
  total: number
}

export interface HindsightBankStatsResponse {
  total_facts: number
  upstream_total?: number | null
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



export type ProviderPanelStatus = 'active' | 'off-limits' | 'exhausted' | 'misconfigured' | 'unknown'

export interface ProviderFlowUsage {
  flow: string
  instance: 'pc' | 'pi'
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
  instance: 'all' | 'pc' | 'pi'
  generated_at: string
  providers: ProviderStatusItem[]
  summary: ProviderStatusSummary
}



export interface MemoryIngestCheckpoint { source_peer: string; highest_contiguous_seq: number; updated_at?: string | null }
export interface MemoryIngestMetricsResponse { checkpoints: MemoryIngestCheckpoint[]; totals: Record<string, number>; lag_by_source: Record<string, number>; dead_letters: number; last_dead_letter_at?: string | null; recent_attempts?: Array<Record<string, unknown>>; db_path?: string; error?: string | null }
export interface MemoryIngestHealthResponse { backend: string; ok: boolean; db_path?: string | null; error?: string | null; tables?: string[] }
export interface DeadLetterEntry { id: number; source_peer: string; event_id: string; seq: number; reason: string; details?: string | null; payload: unknown; created_at: string }
export interface DeadLetterResponse { entries: DeadLetterEntry[]; error?: string | null }

export type DigestSource = 'arxiv' | 'web' | 'custom' | 'telegram'
export interface DigestEntry { id: string; title: string; summary: string; content?: string | null; source: DigestSource | string; source_url?: string | null; source_instance: 'pc' | 'pi'; tags: string[]; ingested_at: string; updated_at: string; replicated_at?: string | null; replication_seq?: number | null; metadata: Record<string, unknown> }
export interface DigestDayGroup { date: string; entries: DigestEntry[]; count: number }
export interface DigestListResponse { entries: DigestEntry[]; groups: DigestDayGroup[]; total: number; page: number; page_size: number; has_more: boolean }
export interface DigestStatsResponse { total_entries: number; by_source: Record<string, number>; by_instance: Record<string, number>; last_24h: number; last_7d: number; replication_lag_seconds?: number | null }


export interface HarnessStatusResponse { webhook: { url: string; status: string; last_event_at?: string | null; events_24h: number; errors_24h: number }; config: { default_backend: string; worktree_root: string } }
export interface AgentSession { id: string; issue_id: string; issue_title: string; backend: string; status: string; started_at: string; last_updated_at?: string | null; worktree: string; platform?: string | null; message_count?: number | null; source?: string; summary?: string | null }
export interface SessionsResponse { sessions: AgentSession[] }
export interface WorkerInfo { session_id: string; pid: number; backend: string; issue_id: string; runtime_seconds?: number | null; log_file: string }
export interface WorkersResponse { workers: WorkerInfo[] }
export interface OperationFeedEvent { timestamp: string; type: string; source?: string; content?: string; session_id?: string | null; status?: string | null }
export interface OperationsRecentResponse { events: OperationFeedEvent[]; total: number }


declare global {
  interface Window {
    __HERMES_SESSION_TOKEN__?: string
    __HERMES_BASE_PATH__?: string
    __HERMES_PLUGIN_SDK__?: any
    __HERMES_PLUGINS__?: {
      register: (name: string, component: unknown) => void
      registerSlot?: (pluginName: string, slotName: string, component: unknown) => void
    }
  }
}
