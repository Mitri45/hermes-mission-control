import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { shortDateTime, formatDateHeader, formatRelativeTime, formatReplicationLag } from '../lib/format'
import { useAppState } from '../lib/state'
import type { DigestEntry, DigestSource, InstanceFilter, DigestStatsResponse } from '../types'

// ==================== Type Definitions ====================

type SourceFilter = 'all' | DigestSource

interface DetailModalProps {
  entryId: string | null
  isOpen: boolean
  onClose: () => void
}

interface FilterBarProps {
  instanceFilter: InstanceFilter
  sourceFilter: SourceFilter
  onInstanceChange: (instance: InstanceFilter) => void
  onSourceChange: (source: SourceFilter) => void
}

interface DigestCardProps {
  entry: DigestEntry
  onClick: () => void
}

interface DayGroupProps {
  date: string
  entries: DigestEntry[]
  onEntryClick: (entry: DigestEntry) => void
}

interface StatsPanelProps {
  stats: DigestStatsResponse | undefined
  isLoading: boolean
}

interface FreshnessIndicatorProps {
  ingestedAt: string
  replicatedAt?: string | null
  replicationSeq?: number | null
}

// ==================== Constants ====================

const SOURCE_COLORS: Record<DigestSource | string, string> = {
  arxiv: '#ff6b6b',
  web: '#4ecdc4',
  custom: '#95e1d3',
  telegram: '#f7b731',
  all: '#888888',
}

const SOURCE_ICONS: Record<DigestSource | string, string> = {
  arxiv: '📄',
  web: '🌐',
  custom: '✏️',
  telegram: '✈️',
  all: '📋',
}

// ==================== Helper Functions ====================

function getSourceColor(source: string): string {
  return SOURCE_COLORS[source] || '#888888'
}

function getSourceIcon(source: string): string {
  return SOURCE_ICONS[source] || '📋'
}

// ==================== Components ====================

function FreshnessIndicator({ ingestedAt, replicatedAt, replicationSeq }: FreshnessIndicatorProps) {
  const ingested = new Date(ingestedAt)
  const now = new Date()
  const ageMinutes = (now.getTime() - ingested.getTime()) / 60000

  let freshnessClass = 'freshness-fresh'
  if (ageMinutes > 60) freshnessClass = 'freshness-stale'
  if (ageMinutes > 1440) freshnessClass = 'freshness-old'

  const isReplicated = !!replicatedAt

  return (
    <div className="freshness-indicator" title={`Ingested: ${ingested.toISOString()}`}>
      <span className={`freshness-dot ${freshnessClass}`} />
      <span className="freshness-time">{formatRelativeTime(ingestedAt)}</span>
      {isReplicated && (
        <span className="replication-badge" title={`Replicated at ${replicatedAt}`}>
          🔄
          {replicationSeq && <span className="replication-seq">#{replicationSeq}</span>}
        </span>
      )}
    </div>
  )
}

function DigestCard({ entry, onClick }: DigestCardProps) {
  return (
    <div className="digest-card" onClick={onClick} role="button" tabIndex={0}>
      <div className="digest-card-header">
        <span
          className="digest-source-badge"
          style={{ backgroundColor: getSourceColor(entry.source) }}
        >
          {getSourceIcon(entry.source)} {entry.source.toUpperCase()}
        </span>
        <span className={`digest-instance-badge instance-${entry.source_instance}`}>
          {entry.source_instance.toUpperCase()}
        </span>
      </div>

      <h4 className="digest-title">{entry.title}</h4>

      <p className="digest-summary">
        {entry.summary.length > 200
          ? `${entry.summary.substring(0, 200)}...`
          : entry.summary}
      </p>

      <div className="digest-card-footer">
        <FreshnessIndicator
          ingestedAt={entry.ingested_at}
          replicatedAt={entry.replicated_at}
          replicationSeq={entry.replication_seq}
        />
        {entry.source_url && (
          <a
            href={entry.source_url}
            className="digest-source-link"
            onClick={(e) => e.stopPropagation()}
            target="_blank"
            rel="noopener noreferrer"
            title="Open source"
          >
            ↗
          </a>
        )}
      </div>

      {entry.tags.length > 0 && (
        <div className="digest-tags">
          {entry.tags.map((tag) => (
            <span key={tag} className="digest-tag">
              #{tag}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function DayGroup({ date, entries, onEntryClick }: DayGroupProps) {
  return (
    <div className="digest-day-group">
      <div className="digest-day-header">
        <h3 className="digest-day-title">{formatDateHeader(date)}</h3>
        <span className="digest-day-count">{entries.length} entries</span>
      </div>
      <div className="digest-cards-grid">
        {entries.map((entry) => (
          <DigestCard
            key={entry.id}
            entry={entry}
            onClick={() => onEntryClick(entry)}
          />
        ))}
      </div>
    </div>
  )
}

function FilterBar({
  instanceFilter,
  sourceFilter,
  onInstanceChange,
  onSourceChange,
}: FilterBarProps) {
  const instanceLabel: Record<InstanceFilter, string> = {
    all: 'All Instances',
    pc: 'PC Only',
    pi: 'Pi Only',
  }

  const sourceLabel: Record<SourceFilter, string> = {
    all: 'All Sources',
    arxiv: 'arXiv',
    web: 'Web',
    custom: 'Custom',
    telegram: 'Telegram',
  }

  return (
    <div className="digest-filters">
      <div className="filter-group">
        <label>Instance</label>
        <div className="filter-buttons">
          {( ['all', 'pc', 'pi'] as InstanceFilter[]).map((inst) => (
            <button
              key={inst}
              className={`filter-btn ${instanceFilter === inst ? 'active' : ''}`}
              onClick={() => onInstanceChange(inst)}
            >
              {instanceLabel[inst]}
            </button>
          ))}
        </div>
      </div>

      <div className="filter-group">
        <label>Source</label>
        <div className="filter-buttons">
          {( ['all', 'arxiv', 'web', 'custom', 'telegram'] as SourceFilter[]).map((src) => (
            <button
              key={src}
              className={`filter-btn ${sourceFilter === src ? 'active' : ''}`}
              onClick={() => onSourceChange(src)}
            >
              {getSourceIcon(src)} {sourceLabel[src]}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

function StatsPanel({ stats, isLoading }: StatsPanelProps) {
  if (isLoading || !stats) {
    return (
      <div className="digest-stats-panel skeleton">
        <div className="stat-skeleton" />
        <div className="stat-skeleton" />
        <div className="stat-skeleton" />
      </div>
    )
  }

  return (
    <div className="digest-stats-panel">
      <div className="digest-stat">
        <span className="stat-value">{stats.total_entries.toLocaleString()}</span>
        <span className="stat-label">Total</span>
      </div>
      <div className="digest-stat">
        <span className="stat-value">{stats.last_24h}</span>
        <span className="stat-label">Last 24h</span>
      </div>
      <div className="digest-stat">
        <span className="stat-value">{stats.last_7d}</span>
        <span className="stat-label">Last 7d</span>
      </div>
      {stats.replication_lag_seconds !== undefined && stats.replication_lag_seconds !== null && (
        <div className="digest-stat">
          <span className="stat-value">{formatReplicationLag(stats.replication_lag_seconds)}</span>
          <span className="stat-label">Sync Lag</span>
        </div>
      )}
    </div>
  )
}

function DetailModal({ entryId, isOpen, onClose }: DetailModalProps) {
  const detailQuery = useQuery({
    queryKey: ['digest-detail', entryId],
    queryFn: () => api.getDigest(entryId as string),
    enabled: isOpen && !!entryId,
    staleTime: 60000,
  })

  const entry = detailQuery.data?.entry

  if (!isOpen || !entryId) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-digest-detail" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-header-badges">
            {entry && (
              <>
                <span
                  className="digest-source-badge"
                  style={{ backgroundColor: getSourceColor(entry.source) }}
                >
                  {getSourceIcon(entry.source)} {entry.source.toUpperCase()}
                </span>
                <span className={`digest-instance-badge instance-${entry.source_instance}`}>
                  {entry.source_instance.toUpperCase()}
                </span>
              </>
            )}
          </div>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          {detailQuery.isLoading && (
            <div className="state-container state-loading">
              <div className="spinner" />
              <p>Loading digest entry...</p>
            </div>
          )}

          {detailQuery.isError && (
            <div className="state-container state-error">
              <h3>Failed to load digest entry</h3>
              <p>Unable to fetch the full report body.</p>
            </div>
          )}

          {!detailQuery.isLoading && !detailQuery.isError && entry && (
            <>
          <h2 className="digest-detail-title">{entry.title}</h2>

          <div className="digest-detail-meta">
            <FreshnessIndicator
              ingestedAt={entry.ingested_at}
              replicatedAt={entry.replicated_at}
              replicationSeq={entry.replication_seq}
            />
            {entry.source_url && (
              <a
                href={entry.source_url}
                className="btn btn-primary"
                target="_blank"
                rel="noopener noreferrer"
              >
                Open Source ↗
              </a>
            )}
          </div>

          <div className="digest-detail-content">
            <div className="digest-full-content">
              {entry.content || entry.summary}
            </div>
          </div>

          {entry.tags.length > 0 && (
            <div className="digest-detail-tags">
              <h4>Tags</h4>
              <div className="tag-list">
                {entry.tags.map((tag) => (
                  <span key={tag} className="digest-tag">
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="digest-detail-ops">
            <h4>Metadata</h4>
            <div className="ops-metadata">
              <div className="ops-meta-row">
                <span className="ops-meta-label">Entry ID:</span>
                <code className="ops-meta-value">{entry.id}</code>
              </div>
              <div className="ops-meta-row">
                <span className="ops-meta-label">Ingested:</span>
                <span className="ops-meta-value">{shortDateTime(entry.ingested_at)}</span>
              </div>
              <div className="ops-meta-row">
                <span className="ops-meta-label">Updated:</span>
                <span className="ops-meta-value">{shortDateTime(entry.updated_at)}</span>
              </div>
              {entry.replicated_at && (
                <div className="ops-meta-row">
                  <span className="ops-meta-label">Replicated:</span>
                  <span className="ops-meta-value">{shortDateTime(entry.replicated_at)}</span>
                </div>
              )}
              {entry.replication_seq && (
                <div className="ops-meta-row">
                  <span className="ops-meta-label">Replication Seq:</span>
                  <span className="ops-meta-value">#{entry.replication_seq}</span>
                </div>
              )}
            </div>
          </div>

          {Object.keys(entry.metadata).length > 0 && (
            <div className="digest-detail-metadata">
              <h4>Extra Metadata</h4>
              <pre className="metadata-json">
                {JSON.stringify(entry.metadata, null, 2)}
              </pre>
            </div>
          )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ==================== Main Route Component ====================

export function DigestRoute() {
  const { instance: globalInstance } = useAppState()

  // Local state
  const [instanceFilter, setInstanceFilter] = useState<InstanceFilter>(globalInstance)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [selectedEntry, setSelectedEntry] = useState<DigestEntry | null>(null)
  const [page, setPage] = useState(1)

  // Sync local instance filter with global when it changes
  useEffect(() => {
    setInstanceFilter(globalInstance)
  }, [globalInstance])

  // Reset page when filters change
  const handleInstanceChange = (inst: InstanceFilter) => {
    setInstanceFilter(inst)
    setPage(1)
  }

  const handleSourceChange = (src: SourceFilter) => {
    setSourceFilter(src)
    setPage(1)
  }

  // Queries
  const digestsQuery = useQuery({
    queryKey: ['digest-list', instanceFilter, sourceFilter, page],
    queryFn: () =>
      api.getDigests(
        instanceFilter,
        sourceFilter === 'all' ? undefined : sourceFilter,
        page,
        50,
        30, // Last 30 days
      ),
    staleTime: 60000, // 1 minute
    refetchInterval: 60000, // Auto-refresh every minute
  })

  const statsQuery = useQuery({
    queryKey: ['digest-stats', instanceFilter],
    queryFn: () => api.getDigestStats(instanceFilter),
    staleTime: 30000,
    refetchInterval: 30000,
  })

  // Loading and error states
  const isLoading = digestsQuery.isLoading
  const isError = digestsQuery.isError
  const groups = digestsQuery.data?.groups ?? []
  const hasMore = digestsQuery.data?.has_more ?? false
  const total = digestsQuery.data?.total ?? 0

  return (
    <div id="digest-view" className="view">
      <div className="page-header">
        <div className="page-header-main">
          <div>
            <h2 className="page-title">Daily Digest</h2>
            <p className="page-subtitle">
              Browse daily digests from arXiv, web sources, and more
            </p>
          </div>
          <StatsPanel stats={statsQuery.data} isLoading={statsQuery.isLoading} />
        </div>
      </div>

      <FilterBar
        instanceFilter={instanceFilter}
        sourceFilter={sourceFilter}
        onInstanceChange={handleInstanceChange}
        onSourceChange={handleSourceChange}
      />

      {/* Degraded sync warning */}
      {statsQuery.data?.replication_lag_seconds &&
        statsQuery.data.replication_lag_seconds > 300 && (
        <div className="alert alert-warning">
          <span className="alert-icon">⚠</span>
          <span className="alert-message">
            Replication lag detected ({formatReplicationLag(statsQuery.data.replication_lag_seconds)}).
            Some entries may not be synchronized between instances.
          </span>
        </div>
      )}

      {/* Content area */}
      <div className="digest-content">
        {isLoading && (
          <div className="state-container state-loading">
            <div className="spinner" />
            <p>Loading digests...</p>
          </div>
        )}

        {isError && (
          <div className="state-container state-error">
            <h3>Failed to load digests</h3>
            <p>Unable to connect to API</p>
            <button className="btn btn-primary" onClick={() => digestsQuery.refetch()}>
              Retry
            </button>
          </div>
        )}

        {!isLoading && !isError && groups.length === 0 && (
          <div className="state-container state-empty">
            <h3>No digests found</h3>
            <p>
              No digest entries match the current filters.
              <br />
              Try adjusting the instance or source filters above.
            </p>
          </div>
        )}

        {!isLoading && !isError && groups.length > 0 && (
          <>
            <div className="digest-results-info">
              Showing {total} entr{total === 1 ? 'y' : 'ies'}
              {sourceFilter !== 'all' && ` from ${sourceFilter}`}
              {instanceFilter !== 'all' && ` on ${instanceFilter.toUpperCase()}`}
            </div>

            <div className="digest-day-groups">
              {groups.map((group) => (
                <DayGroup
                  key={group.date}
                  date={group.date}
                  entries={group.entries}
                  onEntryClick={setSelectedEntry}
                />
              ))}
            </div>

            {/* Pagination */}
            {hasMore && (
              <div className="digest-pagination">
                <button
                  className="btn btn-primary"
                  onClick={() => setPage((p) => p + 1)}
                  disabled={digestsQuery.isFetching}
                >
                  {digestsQuery.isFetching ? 'Loading...' : 'Load More'}
                </button>
              </div>
            )}
          </>
        )}
      </div>

      <DetailModal
        entryId={selectedEntry?.id ?? null}
        isOpen={!!selectedEntry}
        onClose={() => setSelectedEntry(null)}
      />
    </div>
  )
}
