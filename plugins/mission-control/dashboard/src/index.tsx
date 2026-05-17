import './style.css'

import { missionControlApi } from './api'
import type { FleetStatusResponse, HindsightBankStatsResponse, HindsightFact, HindsightFactsResponse, HindsightHealthResponse, HindsightSource, HindsightStaleFactsResponse, InstanceStatusEnvelope, MissionControlSection, ProviderStatusItem, ProviderStatusResponse, ServiceInfo, SystemStatus, MemoryIngestHealthResponse, MemoryIngestMetricsResponse, DeadLetterResponse, DigestListResponse, DigestStatsResponse, DigestEntry, HarnessStatusResponse, SessionsResponse, WorkersResponse, OperationsRecentResponse, AgentSession, OperationFeedEvent } from './types'

function bytes(value?: number | null): string {
  if (value === null || value === undefined) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let idx = 0
  while (size >= 1024 && idx < units.length - 1) {
    size /= 1024
    idx += 1
  }
  return `${size.toFixed(idx === 0 ? 0 : 1)} ${units[idx]}`
}

function pct(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${Math.round(value)}%`
}

function ratio(used?: number | null, total?: number | null): string {
  if (!used || !total) return '—'
  return `${pct((used / total) * 100)} · ${bytes(used)} / ${bytes(total)}`
}

function serviceSummary(services: ServiceInfo[]): string {
  if (!services.length) return 'No monitored services'
  const running = services.filter((service) => service.status.toLowerCase() === 'running').length
  return `${running}/${services.length} services running`
}

function statusClass(envelope?: InstanceStatusEnvelope | null): string {
  if (!envelope || !envelope.ok || !envelope.status) return 'critical'
  const services = envelope.status.services || []
  if (!services.length) return 'warning'
  const running = services.filter((service) => service.status.toLowerCase() === 'running').length
  if (running === services.length) return 'healthy'
  if (running === 0) return 'critical'
  return 'warning'
}

function InstanceCard(props: { label: string; envelope?: InstanceStatusEnvelope | null }) {
  const sdk = window.__HERMES_PLUGIN_SDK__
  const React = sdk.React
  const { Card, CardHeader, CardTitle, CardContent, Badge } = sdk.components
  const envelope = props.envelope
  const status: SystemStatus | null = envelope?.status ?? null
  const cls = statusClass(envelope)
  const badgeVariant = cls === 'healthy' ? 'default' : 'secondary'

  if (!envelope?.ok || !status) {
    return React.createElement(Card, { className: `mission-control-card mission-control-instance ${cls}` },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, props.label),
      ),
      React.createElement(CardContent, null,
        React.createElement(Badge, { variant: 'secondary' }, 'offline'),
        React.createElement('p', { className: 'mission-control-error-inline' }, envelope?.error || 'No telemetry available'),
      ),
    )
  }

  return React.createElement(Card, { className: `mission-control-card mission-control-instance ${cls}` },
    React.createElement(CardHeader, null,
      React.createElement('div', { className: 'mission-control-card-title-row' },
        React.createElement(CardTitle, null, props.label),
        React.createElement(Badge, { variant: badgeVariant }, cls),
      ),
    ),
    React.createElement(CardContent, null,
      React.createElement('div', { className: 'mission-control-metrics' },
        React.createElement('div', null,
          React.createElement('span', null, 'CPU'),
          React.createElement('strong', null, pct(status.cpu_usage)),
        ),
        React.createElement('div', null,
          React.createElement('span', null, 'Temp'),
          React.createElement('strong', null, status.cpu_temp === null || status.cpu_temp === undefined ? '—' : `${status.cpu_temp.toFixed(1)}°C`),
        ),
        React.createElement('div', null,
          React.createElement('span', null, 'Memory'),
          React.createElement('strong', null, ratio(status.memory_used, status.memory_total)),
        ),
        React.createElement('div', null,
          React.createElement('span', null, 'Disk'),
          React.createElement('strong', null, ratio(status.disk_used, status.disk_total)),
        ),
      ),
      React.createElement('div', { className: 'mission-control-service-summary' }, serviceSummary(status.services)),
      React.createElement('ul', { className: 'mission-control-services' },
        status.services.map((service) => React.createElement('li', { key: service.name },
          React.createElement('span', { className: `dot ${service.status.toLowerCase() === 'running' ? 'ok' : 'bad'}` }),
          React.createElement('span', null, service.name),
          React.createElement('code', null, service.port ? `:${service.port}` : 'process'),
        )),
      ),
      React.createElement('p', { className: 'mission-control-muted' },
        `Tailscale: ${status.tailscale?.ip || status.tailscale?.hostname || (status.tailscale?.running ? 'running' : 'unknown')}`,
      ),
    ),
  )
}

function formatDate(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function HindsightPanel(props: {
  health: HindsightHealthResponse | null
  stats: HindsightBankStatsResponse | null
  facts: HindsightFactsResponse | null
  stale: HindsightStaleFactsResponse | null
  source: HindsightSource
  search: string
  loading: boolean
  onSource: (source: HindsightSource) => void
  onSearch: (value: string) => void
  onRefresh: () => void
}) {
  const sdk = window.__HERMES_PLUGIN_SDK__
  const React = sdk.React
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button } = sdk.components
  const facts = props.facts?.items ?? []
  const contexts = Object.entries(props.stats?.facts_per_context ?? {}).slice(0, 8)
  const staleItems = props.stale?.items ?? []
  const healthTone = props.health?.ok ? 'healthy' : 'warning'

  return React.createElement('section', null,
    React.createElement('div', { className: 'mission-control-section-heading' },
      React.createElement('h2', null, 'Hindsight Bank'),
      React.createElement('p', null, props.health ? `${props.health.bank_id} · ${props.health.ok ? 'reachable' : 'degraded'}` : 'Checking memory bank…'),
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-four' },
      React.createElement(Card, { className: `mission-control-card ${healthTone}` },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Health')),
        React.createElement(CardContent, null,
          React.createElement(Badge, { variant: props.health?.ok ? 'default' : 'secondary' }, props.health?.ok ? 'online' : 'degraded'),
          React.createElement('p', { className: 'mission-control-muted' }, props.health?.error || props.health?.base_url || 'No health result yet'),
        ),
      ),
      React.createElement(Card, { className: 'mission-control-card' },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Facts')),
        React.createElement(CardContent, null,
          React.createElement('div', { className: 'mission-control-big-number' }, String(props.stats?.total_facts ?? '—')),
          React.createElement('p', { className: 'mission-control-muted' }, props.stats?.upstream_total ? `${props.stats.upstream_total} upstream memories` : 'normalized memories'),
        ),
      ),
      React.createElement(Card, { className: 'mission-control-card warning' },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Stale')),
        React.createElement(CardContent, null,
          React.createElement('div', { className: 'mission-control-big-number' }, String(props.stats?.stale_candidates ?? '—')),
          React.createElement('p', { className: 'mission-control-muted' }, 'review candidates'),
        ),
      ),
      React.createElement(Card, { className: 'mission-control-card' },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Storage')),
        React.createElement(CardContent, null,
          React.createElement('div', { className: 'mission-control-big-number' }, bytes(props.stats?.storage_estimate_bytes)),
          React.createElement('p', { className: 'mission-control-muted' }, `Last Pi sync: ${formatDate(props.stats?.last_sync_timestamp)}`),
        ),
      ),
    ),
    React.createElement('div', { className: 'mission-control-memory-toolbar' },
      React.createElement('input', {
        className: 'mission-control-input',
        placeholder: 'Search memory facts…',
        defaultValue: props.search,
        onKeyDown: (event: KeyboardEvent) => {
          const target = event.target as HTMLInputElement
          if (event.key === 'Enter') props.onSearch(target.value.trim())
        },
      }),
      React.createElement('select', {
        className: 'mission-control-input',
        value: props.source,
        onChange: (event: Event) => props.onSource((event.target as HTMLSelectElement).value as HindsightSource),
      },
        React.createElement('option', { value: 'all' }, 'All sources'),
        React.createElement('option', { value: 'pc' }, 'PC'),
        React.createElement('option', { value: 'pi' }, 'Pi'),
      ),
      React.createElement(Button, { onClick: props.onRefresh, disabled: props.loading }, props.loading ? 'Loading…' : 'Refresh bank'),
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-two mission-control-memory-layout' },
      React.createElement(Card, { className: 'mission-control-card mission-control-memory-browser' },
        React.createElement(CardHeader, null,
          React.createElement('div', { className: 'mission-control-card-title-row' },
            React.createElement(CardTitle, null, 'Fact Browser'),
            React.createElement(Badge, { variant: 'secondary' }, `${props.facts?.total ?? 0} matched`),
          ),
        ),
        React.createElement(CardContent, null,
          React.createElement('div', { className: 'mission-control-contexts' },
            contexts.map(([context, count]) => React.createElement('span', { key: context, className: 'mission-control-chip' }, `${context || 'uncategorized'} ${count}`)),
          ),
          React.createElement('div', { className: 'mission-control-fact-list' },
            facts.map((fact: HindsightFact) => React.createElement('article', { key: fact.id, className: 'mission-control-fact' },
              React.createElement('div', { className: 'mission-control-fact-meta' },
                React.createElement('span', { className: `mission-control-source source-${fact.source_peer}` }, fact.source_peer.toUpperCase()),
                React.createElement('span', null, fact.context || 'uncategorized'),
                React.createElement('span', null, formatDate(fact.timestamp)),
              ),
              React.createElement('p', null, fact.content || '—'),
              fact.stale_reasons.length ? React.createElement('ul', { className: 'mission-control-stale-reasons' }, fact.stale_reasons.map((reason) => React.createElement('li', { key: reason }, reason))) : null,
            )),
            !facts.length ? React.createElement('p', { className: 'mission-control-muted' }, props.loading ? 'Loading facts…' : 'No facts matched current filters.') : null,
          ),
        ),
      ),
      React.createElement(Card, { className: 'mission-control-card mission-control-stale-panel' },
        React.createElement(CardHeader, null,
          React.createElement('div', { className: 'mission-control-card-title-row' },
            React.createElement(CardTitle, null, 'Stale Review Queue'),
            React.createElement(Badge, { variant: 'secondary' }, `${props.stale?.total ?? 0} candidates`),
          ),
        ),
        React.createElement(CardContent, null,
          React.createElement('div', { className: 'mission-control-fact-list' },
            staleItems.slice(0, 8).map((fact: HindsightFact) => React.createElement('article', { key: fact.id, className: 'mission-control-fact stale' },
              React.createElement('div', { className: 'mission-control-fact-meta' },
                React.createElement('span', { className: `mission-control-source source-${fact.source_peer}` }, fact.source_peer.toUpperCase()),
                React.createElement('span', null, fact.context || 'uncategorized'),
              ),
              React.createElement('p', null, fact.content || '—'),
              React.createElement('ul', { className: 'mission-control-stale-reasons' }, fact.stale_reasons.map((reason) => React.createElement('li', { key: reason }, reason))),
            )),
            !staleItems.length ? React.createElement('p', { className: 'mission-control-muted' }, 'No stale candidates detected.') : null,
          ),
        ),
      ),
    ),
  )
}

function ProviderPanel(props: { status: ProviderStatusResponse | null }) {
  const sdk = window.__HERMES_PLUGIN_SDK__
  const React = sdk.React
  const { Card, CardHeader, CardTitle, CardContent, Badge } = sdk.components
  const providers = props.status?.providers ?? []
  const summary = props.status?.summary
  const badgeVariant = (status: string) => status === 'active' ? 'default' : 'secondary'
  return React.createElement('section', null,
    React.createElement('div', { className: 'mission-control-section-heading' },
      React.createElement('h2', null, 'Provider Status'),
      React.createElement('p', null, props.status ? `Updated ${formatDate(props.status.generated_at)}` : 'Checking configured model providers…'),
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-four' },
      React.createElement(Card, { className: 'mission-control-card' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Total')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(summary?.total ?? '—')))),
      React.createElement(Card, { className: 'mission-control-card healthy' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Active')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(summary?.active ?? '—')))),
      React.createElement(Card, { className: 'mission-control-card warning' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Misconfigured')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(summary?.misconfigured ?? '—')))),
      React.createElement(Card, { className: 'mission-control-card warning' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Off-limits')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(summary?.off_limits ?? '—')))),
    ),
    React.createElement('div', { className: 'mission-control-provider-list' },
      providers.map((provider: ProviderStatusItem) => React.createElement(Card, { key: provider.provider, className: `mission-control-card mission-control-provider provider-${provider.status}` },
        React.createElement(CardHeader, null,
          React.createElement('div', { className: 'mission-control-card-title-row' },
            React.createElement(CardTitle, null, provider.name),
            React.createElement(Badge, { variant: badgeVariant(provider.status) }, provider.status),
          ),
        ),
        React.createElement(CardContent, null,
          React.createElement('div', { className: 'mission-control-provider-meta' },
            React.createElement('span', null, provider.provider),
            React.createElement('span', null, provider.current_model || 'model unknown'),
            React.createElement('span', null, provider.key_source ? `key: ${provider.key_source}` : 'no key source'),
          ),
          React.createElement('p', { className: 'mission-control-muted' }, provider.status_reason || 'No status reason.'),
          React.createElement('div', { className: 'mission-control-provider-flows' },
            provider.primary_flows.map((flow) => React.createElement('span', { key: `${provider.provider}-${flow.flow}-${flow.instance}`, className: 'mission-control-chip' }, `${flow.flow} · ${flow.instance.toUpperCase()}${flow.model ? ` · ${flow.model}` : ''}`)),
          ),
        ),
      )),
      !providers.length ? React.createElement('p', { className: 'mission-control-muted' }, 'No provider configuration discovered.') : null,
    ),
  )
}


function MemoryIngestPanel(props: { health: MemoryIngestHealthResponse | null; metrics: MemoryIngestMetricsResponse | null; deadLetters: DeadLetterResponse | null }) {
  const sdk = window.__HERMES_PLUGIN_SDK__
  const React = sdk.React
  const { Card, CardHeader, CardTitle, CardContent, Badge } = sdk.components
  const totals = props.metrics?.totals ?? {}
  const checkpoints = props.metrics?.checkpoints ?? []
  const deadLetters = props.deadLetters?.entries ?? []
  return React.createElement('section', null,
    React.createElement('div', { className: 'mission-control-section-heading' },
      React.createElement('h2', null, 'Memory Ingest'),
      React.createElement('p', null, props.health ? `${props.health.backend} · ${props.health.ok ? 'database ready' : 'degraded'}` : 'Checking ingest pipeline…'),
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-four' },
      React.createElement(Card, { className: `mission-control-card ${props.health?.ok ? 'healthy' : 'warning'}` }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Health')), React.createElement(CardContent, null, React.createElement(Badge, { variant: props.health?.ok ? 'default' : 'secondary' }, props.health?.ok ? 'ready' : 'degraded'), React.createElement('p', { className: 'mission-control-muted' }, props.health?.error || props.health?.db_path || 'No result yet'))),
      React.createElement(Card, { className: 'mission-control-card' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Applied')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(totals.applied ?? 0)))) ,
      React.createElement(Card, { className: 'mission-control-card warning' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Transient')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(totals.transient_error ?? 0)))) ,
      React.createElement(Card, { className: 'mission-control-card critical' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Dead Letters')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(props.metrics?.dead_letters ?? 0)), React.createElement('p', { className: 'mission-control-muted' }, `last: ${formatDate(props.metrics?.last_dead_letter_at)}`))),
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-two' },
      React.createElement(Card, { className: 'mission-control-card' },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Checkpoints')),
        React.createElement(CardContent, null,
          checkpoints.map((checkpoint) => React.createElement('div', { key: checkpoint.source_peer, className: 'mission-control-row' },
            React.createElement('span', null, checkpoint.source_peer),
            React.createElement('code', null, `seq ${checkpoint.highest_contiguous_seq}`),
            React.createElement('span', null, `lag ${props.metrics?.lag_by_source?.[checkpoint.source_peer] ?? 0}`),
          )),
          !checkpoints.length ? React.createElement('p', { className: 'mission-control-muted' }, props.metrics?.error || 'No source checkpoints yet.') : null,
        ),
      ),
      React.createElement(Card, { className: 'mission-control-card' },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Dead Letter Samples')),
        React.createElement(CardContent, null,
          deadLetters.map((entry) => React.createElement('article', { key: entry.id, className: 'mission-control-fact stale' },
            React.createElement('div', { className: 'mission-control-fact-meta' },
              React.createElement('span', null, entry.source_peer),
              React.createElement('span', null, `seq ${entry.seq}`),
              React.createElement('span', null, formatDate(entry.created_at)),
            ),
            React.createElement('p', null, `${entry.reason}${entry.details ? ` — ${entry.details}` : ''}`),
          )),
          !deadLetters.length ? React.createElement('p', { className: 'mission-control-muted' }, props.deadLetters?.error || 'No dead letters.') : null,
        ),
      ),
    ),
  )
}

function DigestPanel(props: { stats: DigestStatsResponse | null; list: DigestListResponse | null }) {
  const sdk = window.__HERMES_PLUGIN_SDK__
  const React = sdk.React
  const { Card, CardHeader, CardTitle, CardContent, Badge } = sdk.components
  const entries = props.list?.entries ?? []
  return React.createElement('section', null,
    React.createElement('div', { className: 'mission-control-section-heading' },
      React.createElement('h2', null, 'Daily Digest'),
      React.createElement('p', null, props.list ? `${props.list.total} entries in the last 30 days view` : 'Loading digest entries…'),
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-four' },
      React.createElement(Card, { className: 'mission-control-card' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Total')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(props.stats?.total_entries ?? '—')))),
      React.createElement(Card, { className: 'mission-control-card healthy' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, '24h')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(props.stats?.last_24h ?? '—')))),
      React.createElement(Card, { className: 'mission-control-card' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, '7d')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(props.stats?.last_7d ?? '—')))),
      React.createElement(Card, { className: 'mission-control-card warning' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Sources')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-chip-row' }, Object.entries(props.stats?.by_source ?? {}).map(([source, count]) => React.createElement('span', { key: source, className: 'mission-control-chip' }, `${source} ${count}`))))),
    ),
    React.createElement('div', { className: 'mission-control-digest-list' },
      entries.map((entry: DigestEntry) => React.createElement(Card, { key: entry.id, className: 'mission-control-card mission-control-digest-card' },
        React.createElement(CardHeader, null,
          React.createElement('div', { className: 'mission-control-card-title-row' },
            React.createElement(CardTitle, null, entry.title),
            React.createElement(Badge, { variant: 'secondary' }, `${entry.source} · ${entry.source_instance.toUpperCase()}`),
          ),
        ),
        React.createElement(CardContent, null,
          React.createElement('p', null, entry.summary || '—'),
          React.createElement('div', { className: 'mission-control-fact-meta' },
            React.createElement('span', null, formatDate(entry.ingested_at)),
            entry.source_url ? React.createElement('a', { href: entry.source_url, target: '_blank', rel: 'noreferrer' }, 'source ↗') : null,
          ),
          entry.tags?.length ? React.createElement('div', { className: 'mission-control-chip-row' }, entry.tags.slice(0, 8).map((tag) => React.createElement('span', { key: tag, className: 'mission-control-chip' }, `#${tag}`))) : null,
        ),
      )),
      !entries.length ? React.createElement('p', { className: 'mission-control-muted' }, 'No digest entries found.') : null,
    ),
  )
}


function HarnessOpsPanel(props: { harness: HarnessStatusResponse | null; sessions: SessionsResponse | null; workers: WorkersResponse | null; operations: OperationsRecentResponse | null }) {
  const sdk = window.__HERMES_PLUGIN_SDK__
  const React = sdk.React
  const { Card, CardHeader, CardTitle, CardContent, Badge } = sdk.components
  const sessions = props.sessions?.sessions ?? []
  const workers = props.workers?.workers ?? []
  const events = props.operations?.events ?? []
  const webhook = props.harness?.webhook
  return React.createElement('section', null,
    React.createElement('div', { className: 'mission-control-section-heading' },
      React.createElement('h2', null, 'Linear Harness + Operations'),
      React.createElement('p', null, webhook ? `${webhook.status} · ${webhook.events_24h} webhook/log events` : 'Checking harness state…'),
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-four' },
      React.createElement(Card, { className: `mission-control-card ${webhook?.status === 'healthy' ? 'healthy' : 'warning'}` }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Webhook')), React.createElement(CardContent, null, React.createElement(Badge, { variant: webhook?.status === 'healthy' ? 'default' : 'secondary' }, webhook?.status || 'unknown'), React.createElement('p', { className: 'mission-control-muted' }, webhook?.url || 'No webhook URL discovered'))),
      React.createElement(Card, { className: 'mission-control-card' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Sessions')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(sessions.length)))),
      React.createElement(Card, { className: 'mission-control-card healthy' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Workers')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(workers.length)))) ,
      React.createElement(Card, { className: 'mission-control-card' }, React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Ops Events')), React.createElement(CardContent, null, React.createElement('div', { className: 'mission-control-big-number' }, String(props.operations?.total ?? 0)))) ,
    ),
    React.createElement('div', { className: 'mission-control-grid mission-control-grid-two' },
      React.createElement(Card, { className: 'mission-control-card' },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Recent Sessions')),
        React.createElement(CardContent, null,
          sessions.slice(0, 8).map((session: AgentSession) => React.createElement('article', { key: session.id, className: 'mission-control-fact' },
            React.createElement('div', { className: 'mission-control-fact-meta' },
              React.createElement('span', null, session.issue_id),
              React.createElement('span', null, session.backend),
              React.createElement('span', null, session.status),
              React.createElement('span', null, formatDate(session.last_updated_at || session.started_at)),
            ),
            React.createElement('p', null, session.issue_title || session.summary || session.id),
          )),
          !sessions.length ? React.createElement('p', { className: 'mission-control-muted' }, 'No recent sessions found.') : null,
        ),
      ),
      React.createElement(Card, { className: 'mission-control-card' },
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, 'Recent Operations')),
        React.createElement(CardContent, null,
          events.slice(-12).reverse().map((event: OperationFeedEvent, index: number) => React.createElement('article', { key: `${event.timestamp}-${index}`, className: `mission-control-fact ${event.type === 'error' ? 'stale' : ''}` },
            React.createElement('div', { className: 'mission-control-fact-meta' },
              React.createElement('span', null, event.type),
              React.createElement('span', null, event.source || 'log'),
              React.createElement('span', null, formatDate(event.timestamp)),
            ),
            React.createElement('p', null, event.content || '—'),
          )),
          !events.length ? React.createElement('p', { className: 'mission-control-muted' }, 'No recent operation events found.') : null,
        ),
      ),
    ),
  )
}

function SectionCard(props: { section: MissionControlSection }) {
  const sdk = window.__HERMES_PLUGIN_SDK__
  const React = sdk.React
  const { Card, CardHeader, CardTitle, CardContent, Badge } = sdk.components
  const ready = props.section.status === 'ready'
  return React.createElement(Card, { className: 'mission-control-card mission-control-section-card' },
    React.createElement(CardHeader, null,
      React.createElement(CardTitle, null, props.section.label),
    ),
    React.createElement(CardContent, null,
      React.createElement(Badge, { variant: ready ? 'default' : 'secondary' }, props.section.status),
      React.createElement('p', null, ready ? 'Live in native dashboard plugin.' : 'Still served by old Mission Control until migrated.'),
    ),
  )
}

function MissionControlRoot() {
  const sdk = window.__HERMES_PLUGIN_SDK__
  if (!sdk) return null

  const React = sdk.React
  const { useEffect, useState } = sdk.hooks
  const { Button } = sdk.components

  const stateSummary = useState(null)
  const summary = stateSummary[0]
  const setSummary = stateSummary[1]
  const stateFleet = useState(null)
  const fleet: FleetStatusResponse | null = stateFleet[0]
  const setFleet = stateFleet[1]
  const stateHindsightHealth = useState(null)
  const hindsightHealth: HindsightHealthResponse | null = stateHindsightHealth[0]
  const setHindsightHealth = stateHindsightHealth[1]
  const stateHindsightStats = useState(null)
  const hindsightStats: HindsightBankStatsResponse | null = stateHindsightStats[0]
  const setHindsightStats = stateHindsightStats[1]
  const stateHindsightFacts = useState(null)
  const hindsightFacts: HindsightFactsResponse | null = stateHindsightFacts[0]
  const setHindsightFacts = stateHindsightFacts[1]
  const stateHindsightStale = useState(null)
  const hindsightStale: HindsightStaleFactsResponse | null = stateHindsightStale[0]
  const setHindsightStale = stateHindsightStale[1]
  const stateHindsightSource = useState('all')
  const hindsightSource: HindsightSource = stateHindsightSource[0]
  const setHindsightSource = stateHindsightSource[1]
  const stateHindsightSearch = useState('')
  const hindsightSearch = stateHindsightSearch[0]
  const setHindsightSearch = stateHindsightSearch[1]
  const stateProviderStatus = useState(null)
  const providerStatus: ProviderStatusResponse | null = stateProviderStatus[0]
  const setProviderStatus = stateProviderStatus[1]
  const stateMemoryIngestHealth = useState(null)
  const memoryIngestHealth: MemoryIngestHealthResponse | null = stateMemoryIngestHealth[0]
  const setMemoryIngestHealth = stateMemoryIngestHealth[1]
  const stateMemoryIngestMetrics = useState(null)
  const memoryIngestMetrics: MemoryIngestMetricsResponse | null = stateMemoryIngestMetrics[0]
  const setMemoryIngestMetrics = stateMemoryIngestMetrics[1]
  const stateDeadLetters = useState(null)
  const deadLetters: DeadLetterResponse | null = stateDeadLetters[0]
  const setDeadLetters = stateDeadLetters[1]
  const stateDigestStats = useState(null)
  const digestStats: DigestStatsResponse | null = stateDigestStats[0]
  const setDigestStats = stateDigestStats[1]
  const stateDigestList = useState(null)
  const digestList: DigestListResponse | null = stateDigestList[0]
  const setDigestList = stateDigestList[1]
  const stateHarness = useState(null)
  const harness: HarnessStatusResponse | null = stateHarness[0]
  const setHarness = stateHarness[1]
  const stateSessions = useState(null)
  const sessions: SessionsResponse | null = stateSessions[0]
  const setSessions = stateSessions[1]
  const stateWorkers = useState(null)
  const workers: WorkersResponse | null = stateWorkers[0]
  const setWorkers = stateWorkers[1]
  const stateOperations = useState(null)
  const operations: OperationsRecentResponse | null = stateOperations[0]
  const setOperations = stateOperations[1]
  const stateError = useState('')
  const error = stateError[0]
  const setError = stateError[1]
  const stateLoading = useState(true)
  const loading = stateLoading[0]
  const setLoading = stateLoading[1]

  const load = () => {
    setLoading(true)
    setError('')
    Promise.all([
      missionControlApi.summary(),
      missionControlApi.fleetStatus(),
      missionControlApi.hindsightHealth(),
      missionControlApi.hindsightStats(hindsightSource),
      missionControlApi.hindsightFacts({ q: hindsightSearch || undefined, source: hindsightSource, limit: 25 }),
      missionControlApi.hindsightStale(hindsightSource),
      missionControlApi.providerStatus(),
      missionControlApi.memoryIngestHealth(),
      missionControlApi.memoryIngestMetrics(),
      missionControlApi.memoryIngestDeadLetters(),
      missionControlApi.digestStats(),
      missionControlApi.digestList(),
      missionControlApi.harnessStatus(),
      missionControlApi.harnessSessions(),
      missionControlApi.harnessWorkers(),
      missionControlApi.operationsRecent(),
    ])
      .then(([nextSummary, nextFleet, nextHindsightHealth, nextHindsightStats, nextHindsightFacts, nextHindsightStale, nextProviderStatus, nextMemoryIngestHealth, nextMemoryIngestMetrics, nextDeadLetters, nextDigestStats, nextDigestList, nextHarness, nextSessions, nextWorkers, nextOperations]) => {
        setSummary(nextSummary)
        setFleet(nextFleet)
        setHindsightHealth(nextHindsightHealth)
        setHindsightStats(nextHindsightStats)
        setHindsightFacts(nextHindsightFacts)
        setHindsightStale(nextHindsightStale)
        setProviderStatus(nextProviderStatus)
        setMemoryIngestHealth(nextMemoryIngestHealth)
        setMemoryIngestMetrics(nextMemoryIngestMetrics)
        setDeadLetters(nextDeadLetters)
        setDigestStats(nextDigestStats)
        setDigestList(nextDigestList)
        setHarness(nextHarness)
        setSessions(nextSessions)
        setWorkers(nextWorkers)
        setOperations(nextOperations)
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [hindsightSource, hindsightSearch])

  const sections: MissionControlSection[] = summary?.sections ?? [
    { id: 'fleet-health', label: 'Fleet Health', status: 'ready' },
    { id: 'hindsight', label: 'Hindsight Bank', status: 'ready' },
    { id: 'memory-ingest', label: 'Memory Ingest', status: 'ready' },
    { id: 'linear-harness', label: 'Linear Harness', status: 'ready' },
    { id: 'digest', label: 'Digest', status: 'ready' },
    { id: 'provider-status', label: 'Provider Status', status: 'ready' },
    { id: 'operations', label: 'Operations Stream', status: 'ready' },
  ]

  return React.createElement('div', { className: 'mission-control-plugin' },
    React.createElement('div', { className: 'mission-control-header' },
      React.createElement('div', null,
        React.createElement('p', { className: 'mission-control-kicker' }, 'Ops cockpit'),
        React.createElement('h1', null, 'Mission Control'),
        React.createElement('p', { className: 'mission-control-subtitle' },
          'Native Hermes dashboard plugin replacing the old standalone Mission Control UI.'
        ),
      ),
      React.createElement(Button, { onClick: load, disabled: loading }, loading ? 'Checking…' : 'Refresh'),
    ),
    error ? React.createElement('div', { className: 'mission-control-error' }, error) : null,
    React.createElement('section', null,
      React.createElement('div', { className: 'mission-control-section-heading' },
        React.createElement('h2', null, 'Fleet Health'),
        React.createElement('p', null, fleet ? `Updated ${new Date(fleet.generated_at).toLocaleString()}` : 'Loading telemetry…'),
      ),
      React.createElement('div', { className: 'mission-control-grid mission-control-grid-two' },
        React.createElement(InstanceCard, { label: 'PC', envelope: fleet?.instances?.pc }),
        React.createElement(InstanceCard, { label: 'Pi', envelope: fleet?.instances?.pi }),
      ),
    ),
    React.createElement(HindsightPanel, {
      health: hindsightHealth,
      stats: hindsightStats,
      facts: hindsightFacts,
      stale: hindsightStale,
      source: hindsightSource,
      search: hindsightSearch,
      loading,
      onSource: setHindsightSource,
      onSearch: setHindsightSearch,
      onRefresh: load,
    }),
    React.createElement(ProviderPanel, { status: providerStatus }),
    React.createElement(MemoryIngestPanel, { health: memoryIngestHealth, metrics: memoryIngestMetrics, deadLetters }),
    React.createElement(DigestPanel, { stats: digestStats, list: digestList }),
    React.createElement(HarnessOpsPanel, { harness, sessions, workers, operations }),
    React.createElement('section', null,
      React.createElement('div', { className: 'mission-control-section-heading' },
        React.createElement('h2', null, 'Migration Status'),
        React.createElement('p', null, 'Only unique ops panels are being ported. Generic admin stays in Hermes dashboard.'),
      ),
      React.createElement('div', { className: 'mission-control-grid' },
        sections.map((section: MissionControlSection) => React.createElement(SectionCard, { key: section.id, section })),
      ),
    ),
  )
}

window.__HERMES_PLUGINS__?.register('mission-control', MissionControlRoot)
