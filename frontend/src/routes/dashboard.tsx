import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { formatBytes, parseTimestampMs, percent, ratioPercent, shortDateTime, timeAgo } from '../lib/format'
import { useAppState } from '../lib/state'
import type { InstanceFilter, ServiceInfo } from '../types'

/**
 * DIM-210 docs baseline reviewed on 2026-04-09:
 * - https://tanstack.com/start/latest
 * - https://tanstack.com/router/latest
 * - https://tanstack.com/query/latest
 * - https://tanstack.com/table/latest
 * - https://tanstack.com/form/latest
 * - https://sdk.vercel.ai/docs
 */

type HealthSeverity = 'healthy' | 'warning' | 'critical'

const HEALTH_QUERY_INTERVAL_MS = 15_000
const HEALTH_STALE_WARNING_MS = 45_000
const HEALTH_STALE_CRITICAL_MS = 120_000
const USAGE_WARNING_THRESHOLD = 70
const USAGE_CRITICAL_THRESHOLD = 90
const TEMP_WARNING_THRESHOLD = 70
const TEMP_CRITICAL_THRESHOLD = 85

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)))
}

function severityRank(value: HealthSeverity): number {
  if (value === 'critical') return 3
  if (value === 'warning') return 2
  return 1
}

function maxSeverity(...values: HealthSeverity[]): HealthSeverity {
  return values.reduce<HealthSeverity>((highest, current) => {
    return severityRank(current) > severityRank(highest) ? current : highest
  }, 'healthy')
}

function usageSeverity(value: number): HealthSeverity {
  if (value >= USAGE_CRITICAL_THRESHOLD) return 'critical'
  if (value >= USAGE_WARNING_THRESHOLD) return 'warning'
  return 'healthy'
}

function temperatureSeverity(value?: number | null): HealthSeverity {
  if (value === null || value === undefined) return 'warning'
  if (value >= TEMP_CRITICAL_THRESHOLD) return 'critical'
  if (value >= TEMP_WARNING_THRESHOLD) return 'warning'
  return 'healthy'
}

function freshnessSeverity(valueMs: number): HealthSeverity {
  if (valueMs >= HEALTH_STALE_CRITICAL_MS) return 'critical'
  if (valueMs >= HEALTH_STALE_WARNING_MS) return 'warning'
  return 'healthy'
}

function severityClass(value: HealthSeverity): string {
  return `severity-${value}`
}

function severityLabel(value: HealthSeverity): string {
  if (value === 'critical') return 'Critical'
  if (value === 'warning') return 'Degraded'
  return 'Healthy'
}

function serviceStatusSeverity(service: ServiceInfo): HealthSeverity {
  return service.status.toLowerCase() === 'running' ? 'healthy' : 'critical'
}

function summarizeServiceHealth(services: ServiceInfo[]): {
  severity: HealthSeverity
  running: number
  total: number
} {
  const total = services.length
  const running = services.filter((service) => service.status.toLowerCase() === 'running').length
  if (total === 0) {
    return { severity: 'warning', running: 0, total: 0 }
  }
  if (running === total) {
    return { severity: 'healthy', running, total }
  }
  if (running === 0) {
    return { severity: 'warning', running, total }
  }
  return { severity: 'warning', running, total }
}

function serviceHealthSummaryLabel(health: { running: number; total: number }): string {
  if (health.total === 0) return 'No monitored services'
  if (health.running === 0) return `${health.running}/${health.total} services idle`
  return `${health.running}/${health.total} services running`
}

function formatFreshness(valueMs: number): string {
  if (valueMs < 1000) return '<1s old'
  if (valueMs < 60_000) return `${Math.round(valueMs / 1000)}s old`
  return `${Math.round(valueMs / 60_000)}m old`
}

function tailscaleConnectedSignal(info: { ip?: string | null; hostname?: string | null; funnel?: boolean } | undefined): boolean {
  if (!info) return false
  return Boolean(info.ip || info.hostname || info.funnel)
}

function tailscaleDisplay(info: { ip?: string | null; hostname?: string | null; funnel?: boolean } | undefined): string {
  if (!info) return 'Disconnected'
  if (info.ip) return info.ip
  if (info.hostname) return info.hostname
  if (info.funnel) return 'Connected'
  return 'Disconnected'
}

interface InstanceHealthRow {
  key: InstanceFilter
  severity: HealthSeverity
  summary: string
  details: string
}

interface CompareMetricRow {
  key: 'pc' | 'pi'
  label: string
  value: string
  detail: string
  severity: HealthSeverity
  barWidth: string
}

interface CompareMetricCard {
  key: string
  label: string
  rows: CompareMetricRow[]
}

interface ActivityItem {
  key: string
  icon: string
  title: string
  description: string
  timestamp: string
}

const INSTANCE_LABELS: Record<InstanceFilter, string> = {
  all: 'ALL',
  pc: 'PC',
  pi: 'PI',
}

export function DashboardRoute() {
  const { instance, setInstance } = useAppState()

  const pcStatusQuery = useQuery({
    queryKey: ['dashboard-status', 'pc'],
    queryFn: () => api.getSystemStatus('pc'),
    refetchInterval: HEALTH_QUERY_INTERVAL_MS,
    staleTime: 10_000,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  })
  const piStatusQuery = useQuery({
    queryKey: ['dashboard-status', 'pi'],
    queryFn: () => api.getSystemStatus('pi'),
    refetchInterval: HEALTH_QUERY_INTERVAL_MS,
    staleTime: 10_000,
    retry: 1,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  })
  const harnessQuery = useQuery({
    queryKey: ['dashboard-harness'],
    queryFn: api.getHarnessStatus,
    refetchInterval: HEALTH_QUERY_INTERVAL_MS,
    staleTime: 10_000,
    retry: 2,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
  })
  const cronQuery = useQuery({
    queryKey: ['dashboard-cron', instance],
    queryFn: () => api.getCron(instance),
    refetchInterval: 30_000,
  })
  const sessionsQuery = useQuery({
    queryKey: ['dashboard-sessions', instance],
    queryFn: api.getSessions,
    refetchInterval: 30_000,
  })
  const digestStatsQuery = useQuery({
    queryKey: ['dashboard-digest-stats', instance],
    queryFn: () => api.getDigestStats(instance),
    refetchInterval: 60_000,
  })
  const digestEntriesQuery = useQuery({
    queryKey: ['dashboard-digest-preview', instance],
    queryFn: () => api.getDigests(instance, undefined, 1, 5, 30),
    refetchInterval: 60_000,
  })

  const loading = pcStatusQuery.isLoading || cronQuery.isLoading || sessionsQuery.isLoading || (instance === 'pi' && piStatusQuery.isLoading)
  const hasError = pcStatusQuery.isError || cronQuery.isError || sessionsQuery.isError || (instance === 'pi' && piStatusQuery.isError)

  if (loading) {
    return (
      <div id="loading-state" className="state-container state-loading">
        <div className="spinner" />
        <p>Loading dashboard data...</p>
      </div>
    )
  }

  if (hasError) {
    const primaryError = pcStatusQuery.error ?? piStatusQuery.error ?? cronQuery.error ?? sessionsQuery.error
    const detail = primaryError instanceof Error ? primaryError.message : 'Unable to connect to API'
    return (
      <div id="error-state" className="state-container state-error">
        <h3>Failed to load data</h3>
        <p id="error-message">{detail}</p>
        <button
          className="btn btn-primary"
          onClick={() => {
            void pcStatusQuery.refetch()
            void piStatusQuery.refetch()
            void harnessQuery.refetch()
            void cronQuery.refetch()
            void sessionsQuery.refetch()
            void digestStatsQuery.refetch()
          }}
          id="retry-btn"
        >
          Retry
        </button>
      </div>
    )
  }

  const pcStatus = pcStatusQuery.data
  const piStatus = piStatusQuery.data
  const cron = cronQuery.data?.jobs ?? []
  const sessions = sessionsQuery.data?.sessions ?? []
  const digestStats = digestStatsQuery.data
  const digestPreviewEntries = digestEntriesQuery.data?.entries ?? []
  const runningSessions = sessions.filter((session) => session.status === 'running')
  const activeSessionCount = runningSessions.length
  const sessionsStatusText = activeSessionCount > 0
    ? `${activeSessionCount} active workers`
    : 'No active workers'

  if (!pcStatus || (instance === 'pi' && !piStatus)) {
    return (
      <div id="empty-state" className="state-container state-empty">
        <h3>No data available</h3>
        <p>There is nothing to display right now</p>
      </div>
    )
  }

  const activeStatus = instance === 'pi' ? piStatus ?? pcStatus : pcStatus
  const cpuPercent = activeStatus.cpu_usage
  const memoryPercent = ratioPercent(activeStatus.memory_used, activeStatus.memory_total)
  const diskPercent = ratioPercent(activeStatus.disk_used, activeStatus.disk_total)
  const tempPercent = Math.max(0, Math.min(100, activeStatus.cpu_temp ?? 0))

  const cpuSeverity = usageSeverity(cpuPercent)
  const memorySeverity = usageSeverity(memoryPercent)
  const diskSeverity = usageSeverity(diskPercent)
  const tempSeverity = temperatureSeverity(activeStatus.cpu_temp)

  const serviceHealth = summarizeServiceHealth(activeStatus.services)
  const tailscaleConnected = tailscaleConnectedSignal(activeStatus.tailscale)
  const networkSeverity: HealthSeverity = tailscaleConnected ? 'healthy' : 'warning'
  const systemHealthSource = instance === 'all' ? 'PC + PI comparison' : activeStatus.source_label

  const sourceTimestampMs = parseTimestampMs(activeStatus.timestamp)
  const sourceFreshnessMs = Number.isFinite(sourceTimestampMs)
    ? Math.max(0, Date.now() - sourceTimestampMs)
    : Math.max(0, Date.now() - (instance === 'pi' ? piStatusQuery.dataUpdatedAt : pcStatusQuery.dataUpdatedAt))
  const queryFreshnessMs = Math.max(0, Date.now() - (instance === 'pi' ? piStatusQuery.dataUpdatedAt : pcStatusQuery.dataUpdatedAt))
  const freshnessMs = Math.max(sourceFreshnessMs, queryFreshnessMs)
  const dataFreshnessSeverity = freshnessSeverity(freshnessMs)

  const webhookStatusRaw = harnessQuery.data?.webhook?.status?.toLowerCase()
  const piTelemetryFreshnessMs = piStatus?.timestamp ? Math.max(0, Date.now() - parseTimestampMs(piStatus.timestamp)) : Number.POSITIVE_INFINITY
  const piTelemetryFreshnessSeverity = Number.isFinite(piTelemetryFreshnessMs) ? freshnessSeverity(piTelemetryFreshnessMs) : 'critical'

  const piServiceHealth = piStatus ? summarizeServiceHealth(piStatus.services) : { severity: 'warning' as HealthSeverity, running: 0, total: 0 }
  const piNetworkSeverity: HealthSeverity = tailscaleConnectedSignal(piStatus?.tailscale) ? 'healthy' : 'warning'
  const piCpuSeverity = piStatus ? usageSeverity(piStatus.cpu_usage) : 'warning'
  const piMemorySeverity = piStatus ? usageSeverity(ratioPercent(piStatus.memory_used, piStatus.memory_total)) : 'warning'
  const piDiskSeverity = piStatus ? usageSeverity(ratioPercent(piStatus.disk_used, piStatus.disk_total)) : 'warning'
  const piTempSeverity = piStatus ? temperatureSeverity(piStatus.cpu_temp) : 'warning'

  const piSeverity: HealthSeverity = piStatus
    ? maxSeverity(
        piCpuSeverity,
        piMemorySeverity,
        piDiskSeverity,
        piTempSeverity,
        piServiceHealth.severity,
        piNetworkSeverity,
        piTelemetryFreshnessSeverity,
      )
    : harnessQuery.isError
      ? 'critical'
      : webhookStatusRaw === 'healthy'
        ? 'warning'
        : 'critical'
  const piSummary = piStatus
    ? `${severityLabel(piSeverity)} telemetry`
    : harnessQuery.isError
      ? 'PI telemetry unavailable'
      : webhookStatusRaw === 'healthy'
        ? 'Webhook connected, telemetry unavailable'
        : `Webhook ${webhookStatusRaw ?? 'degraded'}`

  const pcSeverity = maxSeverity(
    usageSeverity(pcStatus.cpu_usage),
    usageSeverity(ratioPercent(pcStatus.memory_used, pcStatus.memory_total)),
    usageSeverity(ratioPercent(pcStatus.disk_used, pcStatus.disk_total)),
    temperatureSeverity(pcStatus.cpu_temp),
    summarizeServiceHealth(pcStatus.services).severity,
    tailscaleConnectedSignal(pcStatus.tailscale) ? 'healthy' : 'warning',
    freshnessSeverity(
      pcStatus.timestamp ? Math.max(0, Date.now() - parseTimestampMs(pcStatus.timestamp)) : Math.max(0, Date.now() - pcStatusQuery.dataUpdatedAt),
    ),
  )
  const allSeverity = maxSeverity(pcSeverity, piSeverity)

  const healthRows: InstanceHealthRow[] = [
    {
      key: 'all',
      severity: allSeverity,
      summary: `${severityLabel(allSeverity)} overall`,
      details: `PC ${severityLabel(pcSeverity)} • PI ${severityLabel(piSeverity)}`,
    },
    {
      key: 'pc',
      severity: pcSeverity,
      summary: serviceHealthSummaryLabel(summarizeServiceHealth(pcStatus.services)),
      details: `CPU ${percent(pcStatus.cpu_usage)} • RAM ${percent(ratioPercent(pcStatus.memory_used, pcStatus.memory_total))} • Disk ${percent(ratioPercent(pcStatus.disk_used, pcStatus.disk_total))}`,
    },
    {
      key: 'pi',
      severity: piSeverity,
      summary: piSummary,
      details: piStatus
        ? `CPU ${percent(piStatus.cpu_usage)} • RAM ${percent(ratioPercent(piStatus.memory_used, piStatus.memory_total))} • Disk ${percent(ratioPercent(piStatus.disk_used, piStatus.disk_total))}`
        : harnessQuery.isFetching
          ? 'Syncing PI status'
          : 'Remote PI telemetry endpoint unavailable',
    },
  ]

  const scheduled = cron.filter((job) => job.enabled && (job.status === 'active' || job.status === 'scheduled')).length
  const paused = cron.filter((job) => job.status === 'paused').length
  const failed = cron.filter((job) => job.last_result === 'failed').length
  const digestTotal = digestStats?.total_entries ?? 0
  const digest24h = digestStats?.last_24h ?? 0
  const digest7d = digestStats?.last_7d ?? 0
  const digestSourceLabel = instance === 'all' ? 'PC + PI aggregated feed' : `${INSTANCE_LABELS[instance]} digest feed`
  const digestScopeSummary = instance === 'all'
    ? `${Object.keys(digestStats?.by_instance ?? {}).length} instance sources`
    : `${digestStats?.by_instance?.[instance] ?? 0} entries on ${INSTANCE_LABELS[instance]}`
  const digestCardStatus = digestStatsQuery.isError
    ? 'Digest feed unavailable'
    : digestTotal > 0
      ? `${digest24h} in last 24h`
      : 'No digest entries yet'

  function digestPreviewSummary(summary: string): string {
    const normalized = summary.replace(/\s+/g, ' ').trim()
    if (normalized.length <= 72) return normalized
    return `${normalized.slice(0, 69)}...`
  }

  const recentActivity: ActivityItem[] = [
    ...digestPreviewEntries.map((entry) => ({
      key: `digest-${entry.id}`,
      icon: '▤',
      title: entry.title,
      description: digestPreviewSummary(entry.summary),
      timestamp: entry.ingested_at,
    })),
    ...cron
      .filter((job) => job.last_run)
      .map((job) => ({
        key: `cron-${job.id}`,
        icon: '⧗',
        title: job.name,
        description:
          job.last_result === 'failed'
            ? `Cron run failed on ${job.instance.toUpperCase()}`
            : `Cron run completed on ${job.instance.toUpperCase()}`,
        timestamp: job.last_run as string,
      })),
    ...runningSessions.map((session) => ({
      key: `session-${session.id}`,
      icon: '◎',
      title: `Live session ${session.issue_id ?? session.id}`,
      description: `${session.backend} / ${session.status}`,
      timestamp: session.started_at,
    })),
  ]
    .sort((a, b) => parseTimestampMs(b.timestamp) - parseTimestampMs(a.timestamp))
    .slice(0, 5)

  const metricCards = [
    {
      key: 'cpu',
      label: 'CPU',
      value: percent(cpuPercent),
      detail: `${activeStatus.cpu_usage.toFixed(1)}% utilization`,
      severity: cpuSeverity,
      barWidth: `${clampPercent(cpuPercent)}%`,
    },
    {
      key: 'memory',
      label: 'Memory',
      value: percent(memoryPercent),
      detail: `${formatBytes(activeStatus.memory_used)} / ${formatBytes(activeStatus.memory_total)}`,
      severity: memorySeverity,
      barWidth: `${clampPercent(memoryPercent)}%`,
    },
    {
      key: 'disk',
      label: 'Disk',
      value: percent(diskPercent),
      detail: `${formatBytes(activeStatus.disk_used)} / ${formatBytes(activeStatus.disk_total)}`,
      severity: diskSeverity,
      barWidth: `${clampPercent(diskPercent)}%`,
    },
    {
      key: 'temperature',
      label: 'Temperature',
      value: activeStatus.cpu_temp === null || activeStatus.cpu_temp === undefined ? '--' : `${activeStatus.cpu_temp.toFixed(1)}°C`,
      detail: activeStatus.cpu_temp === null || activeStatus.cpu_temp === undefined ? 'Thermal sensor unavailable' : 'CPU thermal envelope',
      severity: tempSeverity,
      barWidth: `${clampPercent(tempPercent)}%`,
    },
  ]

  const compareMetricCards: CompareMetricCard[] = piStatus ? [
    {
      key: 'cpu',
      label: 'CPU',
      rows: [
        {
          key: 'pc',
          label: 'PC',
          value: percent(pcStatus.cpu_usage),
          detail: `${pcStatus.cpu_usage.toFixed(1)}% utilization`,
          severity: usageSeverity(pcStatus.cpu_usage),
          barWidth: `${clampPercent(pcStatus.cpu_usage)}%`,
        },
        {
          key: 'pi',
          label: 'PI',
          value: percent(piStatus.cpu_usage),
          detail: `${piStatus.cpu_usage.toFixed(1)}% utilization`,
          severity: usageSeverity(piStatus.cpu_usage),
          barWidth: `${clampPercent(piStatus.cpu_usage)}%`,
        },
      ],
    },
    {
      key: 'memory',
      label: 'Memory',
      rows: [
        {
          key: 'pc',
          label: 'PC',
          value: percent(ratioPercent(pcStatus.memory_used, pcStatus.memory_total)),
          detail: `${formatBytes(pcStatus.memory_used)} / ${formatBytes(pcStatus.memory_total)}`,
          severity: usageSeverity(ratioPercent(pcStatus.memory_used, pcStatus.memory_total)),
          barWidth: `${clampPercent(ratioPercent(pcStatus.memory_used, pcStatus.memory_total))}%`,
        },
        {
          key: 'pi',
          label: 'PI',
          value: percent(ratioPercent(piStatus.memory_used, piStatus.memory_total)),
          detail: `${formatBytes(piStatus.memory_used)} / ${formatBytes(piStatus.memory_total)}`,
          severity: usageSeverity(ratioPercent(piStatus.memory_used, piStatus.memory_total)),
          barWidth: `${clampPercent(ratioPercent(piStatus.memory_used, piStatus.memory_total))}%`,
        },
      ],
    },
    {
      key: 'disk',
      label: 'Disk',
      rows: [
        {
          key: 'pc',
          label: 'PC',
          value: percent(ratioPercent(pcStatus.disk_used, pcStatus.disk_total)),
          detail: `${formatBytes(pcStatus.disk_used)} / ${formatBytes(pcStatus.disk_total)}`,
          severity: usageSeverity(ratioPercent(pcStatus.disk_used, pcStatus.disk_total)),
          barWidth: `${clampPercent(ratioPercent(pcStatus.disk_used, pcStatus.disk_total))}%`,
        },
        {
          key: 'pi',
          label: 'PI',
          value: percent(ratioPercent(piStatus.disk_used, piStatus.disk_total)),
          detail: `${formatBytes(piStatus.disk_used)} / ${formatBytes(piStatus.disk_total)}`,
          severity: usageSeverity(ratioPercent(piStatus.disk_used, piStatus.disk_total)),
          barWidth: `${clampPercent(ratioPercent(piStatus.disk_used, piStatus.disk_total))}%`,
        },
      ],
    },
    {
      key: 'temperature',
      label: 'Temperature',
      rows: [
        {
          key: 'pc',
          label: 'PC',
          value: pcStatus.cpu_temp === null || pcStatus.cpu_temp === undefined ? '--' : `${pcStatus.cpu_temp.toFixed(1)}°C`,
          detail: pcStatus.cpu_temp === null || pcStatus.cpu_temp === undefined ? 'Thermal sensor unavailable' : 'CPU thermal envelope',
          severity: temperatureSeverity(pcStatus.cpu_temp),
          barWidth: `${clampPercent(Math.max(0, Math.min(100, pcStatus.cpu_temp ?? 0)))}%`,
        },
        {
          key: 'pi',
          label: 'PI',
          value: piStatus.cpu_temp === null || piStatus.cpu_temp === undefined ? '--' : `${piStatus.cpu_temp.toFixed(1)}°C`,
          detail: piStatus.cpu_temp === null || piStatus.cpu_temp === undefined ? 'Thermal sensor unavailable' : 'CPU thermal envelope',
          severity: temperatureSeverity(piStatus.cpu_temp),
          barWidth: `${clampPercent(Math.max(0, Math.min(100, piStatus.cpu_temp ?? 0)))}%`,
        },
      ],
    },
  ] : []

  return (
    <div id="dashboard-view" className="view">
      <div className="page-header">
        <h2 className="page-title">Dashboard</h2>
        <p className="page-subtitle">System health and key operational metrics</p>
      </div>

      <section className="section health-panel" id="system-health-panel">
        <div className="health-panel-header">
          <div>
            <h3 className="section-title">System Health</h3>
            <p className="health-panel-subtitle">
              Source: {systemHealthSource} • Selected instance: {INSTANCE_LABELS[instance]}
            </p>
          </div>
          <div className={`health-overall-pill ${severityClass(allSeverity)}`}>
            <span className="health-overall-label">Overall</span>
            <span className="health-overall-value">{severityLabel(allSeverity)}</span>
          </div>
        </div>

        <div className="health-meta-row">
          <span className="health-meta-item">Telemetry source: {systemHealthSource}</span>
          <span className="health-meta-item">Telemetry: {shortDateTime(activeStatus.timestamp)}</span>
          <span className="health-meta-item">Relative: {timeAgo(activeStatus.timestamp)}</span>
          <span className={`health-meta-item ${severityClass(dataFreshnessSeverity)}`}>
            Freshness: {formatFreshness(freshnessMs)}
          </span>
        </div>

        <div className="health-metrics-grid">
          {instance === 'all' && piStatus ? compareMetricCards.map((metric) => (
            <article key={metric.key} className="health-metric-card">
              <div className="health-metric-top">
                <span className="health-metric-label">{metric.label}</span>
              </div>
              <div className="health-compare-list">
                {metric.rows.map((row) => (
                  <div key={row.key} className="health-compare-row">
                    <div className="health-compare-top">
                      <span className="health-compare-key">{row.label}</span>
                      <span className={`health-compare-value ${severityClass(row.severity)}`}>{row.value}</span>
                    </div>
                    <div className="health-metric-detail">{row.detail}</div>
                    <div className="progress-bar">
                      <div className={`progress-fill ${severityClass(row.severity)}`} style={{ width: row.barWidth }} />
                    </div>
                  </div>
                ))}
              </div>
            </article>
          )) : metricCards.map((metric) => (
            <article key={metric.key} className={`health-metric-card ${severityClass(metric.severity)}`}>
              <div className="health-metric-top">
                <span className="health-metric-label">{metric.label}</span>
                <span className="health-metric-value">{metric.value}</span>
              </div>
              <div className="health-metric-detail">{metric.detail}</div>
              <div className="progress-bar">
                <div className={`progress-fill ${severityClass(metric.severity)}`} style={{ width: metric.barWidth }} />
              </div>
            </article>
          ))}
        </div>

        <div className="health-signal-grid">
          <article className="health-signal-card">
            <h4 className="health-signal-title">Service Status</h4>
            {instance === 'all' && piStatus ? (
              <div className="health-compare-list">
                {[
                  {
                    key: 'pc',
                    label: 'PC',
                    summary: summarizeServiceHealth(pcStatus.services),
                    services: pcStatus.services,
                  },
                  {
                    key: 'pi',
                    label: 'PI',
                    summary: summarizeServiceHealth(piStatus.services),
                    services: piStatus.services,
                  },
                ].map((group) => (
                  <div key={group.key} className="health-compare-block">
                    <div className="health-signal-summary">
                      <span className="health-compare-key">{group.label}</span>
                      <span className={`health-dot ${severityClass(group.summary.severity)}`} />
                      <span>{group.summary.running}/{group.summary.total} running</span>
                    </div>
                    <div className="health-service-list">
                      {group.services.map((service) => (
                        <div className="health-service-item" key={`${group.key}-${service.name}`}>
                          <span className={`health-dot ${severityClass(serviceStatusSeverity(service))}`} />
                          <span className="health-service-name">{service.name}</span>
                          <span className="health-service-meta">
                            {service.status}
                            {service.port ? ` · :${service.port}` : ''}
                            {service.pid ? ` · pid ${service.pid}` : ''}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <>
                <div className="health-signal-summary">
                  <span className={`health-dot ${severityClass(serviceHealth.severity)}`} />
                  <span>{serviceHealth.running}/{serviceHealth.total} running</span>
                </div>
                <div className="health-service-list">
                  {activeStatus.services.map((service) => (
                    <div className="health-service-item" key={service.name}>
                      <span className={`health-dot ${severityClass(serviceStatusSeverity(service))}`} />
                      <span className="health-service-name">{service.name}</span>
                      <span className="health-service-meta">
                        {service.status}
                        {service.port ? ` · :${service.port}` : ''}
                        {service.pid ? ` · pid ${service.pid}` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </article>

          <article className="health-signal-card">
            <h4 className="health-signal-title">Network</h4>
            {instance === 'all' && piStatus ? (
              <div className="health-compare-list">
                <div className="health-compare-block">
                  <div className="health-signal-summary">
                    <span className="health-compare-key">PC</span>
                  </div>
                  <div className="health-service-item">
                    <span className={`health-dot ${severityClass(tailscaleConnectedSignal(pcStatus.tailscale) ? 'healthy' : 'warning')}`} />
                    <span className="health-service-name">Tailscale</span>
                    <span className="health-service-meta">{tailscaleDisplay(pcStatus.tailscale)}</span>
                  </div>
                  <div className="health-service-item">
                    <span className={`health-dot ${pcStatus.tailscale?.funnel ? 'severity-healthy' : 'severity-warning'}`} />
                    <span className="health-service-name">Funnel</span>
                    <span className="health-service-meta">{pcStatus.tailscale?.funnel ? 'Enabled' : 'Disabled'}</span>
                  </div>
                </div>
                <div className="health-compare-block">
                  <div className="health-signal-summary">
                    <span className="health-compare-key">PI</span>
                  </div>
                  <div className="health-service-item">
                    <span className={`health-dot ${severityClass(tailscaleConnectedSignal(piStatus.tailscale) ? 'healthy' : 'warning')}`} />
                    <span className="health-service-name">Tailscale</span>
                    <span className="health-service-meta">{tailscaleDisplay(piStatus.tailscale)}</span>
                  </div>
                  <div className="health-service-item">
                    <span className={`health-dot ${piStatus.tailscale?.funnel ? 'severity-healthy' : 'severity-warning'}`} />
                    <span className="health-service-name">Funnel</span>
                    <span className="health-service-meta">{piStatus.tailscale?.funnel ? 'Enabled' : 'Disabled'}</span>
                  </div>
                  <div className="health-service-item">
                    <span className={`health-dot ${piSeverity === 'critical' ? 'severity-critical' : piSeverity === 'warning' ? 'severity-warning' : 'severity-healthy'}`} />
                    <span className="health-service-name">Webhook</span>
                    <span className="health-service-meta">{piSummary}</span>
                  </div>
                </div>
              </div>
            ) : (
              <>
                <div className="health-service-item">
                  <span className={`health-dot ${severityClass(networkSeverity)}`} />
                  <span className="health-service-name">Tailscale</span>
                  <span className="health-service-meta">{tailscaleDisplay(activeStatus.tailscale)}</span>
                </div>
                <div className="health-service-item">
                  <span className={`health-dot ${activeStatus.tailscale?.funnel ? 'severity-healthy' : 'severity-warning'}`} />
                  <span className="health-service-name">Funnel</span>
                  <span className="health-service-meta">{activeStatus.tailscale?.funnel ? 'Enabled' : 'Disabled'}</span>
                </div>
                <div className="health-service-item">
                  <span className={`health-dot ${piSeverity === 'critical' ? 'severity-critical' : piSeverity === 'warning' ? 'severity-warning' : 'severity-healthy'}`} />
                  <span className="health-service-name">Webhook</span>
                  <span className="health-service-meta">{piSummary}</span>
                </div>
              </>
            )}
          </article>

          <article className="health-signal-card">
            <h4 className="health-signal-title">Instance Health</h4>
            <div className="instance-health-list">
              {healthRows.map((row) => (
                <button
                  key={row.key}
                  type="button"
                  className={`instance-health-row ${severityClass(row.severity)} ${instance === row.key ? 'active' : ''}`}
                  onClick={() => setInstance(row.key)}
                >
                  <span className="instance-health-key">{row.key.toUpperCase()}</span>
                  <span className="instance-health-summary">{row.summary}</span>
                  <span className="instance-health-detail">{row.details}</span>
                </button>
              ))}
            </div>
          </article>
        </div>
      </section>

      <div className="cards-grid">
        <article className="card card-cron" id="cron-card">
          <div className="card-header">
            <div className="card-icon">⧗</div>
            <h3 className="card-title">Cron Jobs</h3>
            <span className="card-instance" data-instance={instance}>{instance.toUpperCase()}</span>
          </div>
          <div className="card-body">
            <div className="stat-row">
              <div className="stat"><span className="stat-value" id="cron-active">{scheduled}</span><span className="stat-label">Scheduled</span></div>
              <div className="stat"><span className="stat-value" id="cron-paused">{paused}</span><span className="stat-label">Paused</span></div>
              <div className="stat"><span className="stat-value" id="cron-failed">{failed}</span><span className="stat-label">Failed</span></div>
            </div>
            <div className="next-jobs" id="cron-next-jobs">
              {cron
                .filter((job) => job.next_run && job.enabled && (job.status === 'active' || job.status === 'scheduled'))
                .sort((a, b) => new Date(a.next_run!).getTime() - new Date(b.next_run!).getTime())
                .slice(0, 3)
                .map((job) => (
                  <div className="next-job-item" key={job.id}>
                    <span className="next-job-name">{job.name}</span>
                    <span className="next-job-time">{shortDateTime(job.next_run)}</span>
                  </div>
                ))}
            </div>
          </div>
          <div className="card-footer">
            <span className="card-status" id="cron-status">{scheduled} scheduled / {paused} paused</span>
          </div>
        </article>

        <article className="card card-digest" id="digest-card">
          <div className="card-header">
            <div className="card-icon">▤</div>
            <h3 className="card-title">Daily Digest</h3>
            <span className="card-instance" data-instance={instance}>{instance.toUpperCase()}</span>
          </div>
          <div className="card-body">
            <div className="digest-stats-grid" id="digest-summary">
              <div className="digest-item"><span className="digest-count" id="digest-total">{digestStatsQuery.isLoading ? '—' : digestTotal}</span><span className="digest-label">Total</span></div>
              <div className="digest-item"><span className="digest-count" id="digest-24h">{digestStatsQuery.isLoading ? '—' : digest24h}</span><span className="digest-label">Last 24h</span></div>
              <div className="digest-item"><span className="digest-count" id="digest-7d">{digestStatsQuery.isLoading ? '—' : digest7d}</span><span className="digest-label">Last 7d</span></div>
            </div>
            <div className="digest-status" id="digest-last-run">Data source: {digestSourceLabel} • {digestScopeSummary}</div>
            <div className="digest-preview-list" id="digest-preview-list">
              {digestEntriesQuery.isLoading ? (
                <div className="digest-preview-empty">Loading recent entries...</div>
              ) : digestPreviewEntries.length > 0 ? (
                digestPreviewEntries.map((entry) => (
                  <div className="digest-preview-item" key={entry.id}>
                    <div className="digest-preview-head">
                      <span className="digest-preview-title">{entry.title}</span>
                      <span className="digest-preview-time">{shortDateTime(entry.ingested_at)}</span>
                    </div>
                    <div className="digest-preview-summary">{digestPreviewSummary(entry.summary)}</div>
                  </div>
                ))
              ) : (
                <div className="digest-preview-empty">No recent digest entries for this scope.</div>
              )}
            </div>
          </div>
          <div className="card-footer">
            <span className="card-status" id="digest-status">{digestCardStatus}</span>
          </div>
        </article>

        <article className="card card-sessions" id="sessions-card">
          <div className="card-header">
            <div className="card-icon">◎</div>
            <h3 className="card-title">Active Sessions</h3>
            <span className="card-instance" data-instance={instance}>{instance.toUpperCase()}</span>
          </div>
          <div className="card-body">
            <div className="sessions-count">
              <span className="big-number" id="active-sessions">{activeSessionCount}</span>
              <span className="big-label">running sessions</span>
            </div>
            <div className="sessions-list" id="sessions-list">
              {runningSessions.length > 0 ? (
                runningSessions.slice(0, 3).map((session) => (
                  <div className="session-item" key={session.id}>
                    <span className="session-status" />
                    <div className="session-info">
                      <span className="session-id">{session.issue_id ?? session.id}</span>
                      <span className="session-backend">{session.backend}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty-text">No active sessions</div>
              )}
            </div>
          </div>
          <div className="card-footer">
            <span className="card-status" id="sessions-status">{sessionsStatusText}</span>
          </div>
        </article>
      </div>

      <section className="section">
        <h3 className="section-title">Recent Activity</h3>
        <div className="activity-list" id="activity-list">
          {recentActivity.length > 0 ? recentActivity.map((item) => (
            <div className="activity-item" key={item.key}>
              <div className="activity-icon">{item.icon}</div>
              <div className="activity-content">
                <div className="activity-title">{item.title}</div>
                <div className="activity-desc">{item.description}</div>
              </div>
              <div className="activity-time">{shortDateTime(item.timestamp)}</div>
            </div>
          )) : (
            <div className="empty-text">No recent activity</div>
          )}
        </div>
      </section>
    </div>
  )
}
