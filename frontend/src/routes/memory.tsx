import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useForm } from '@tanstack/react-form'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { api } from '../lib/api'
import { shortDateTime } from '../lib/format'
import { useAppState } from '../lib/state'
import type { HindsightFact, HindsightFactDetailResponse, HindsightSource, ProviderStatusItem } from '../types'

const PAGE_SIZE = 25
const columnHelper = createColumnHelper<HindsightFact>()

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function dateOnly(value?: string | null): string {
  if (!value) return '--'
  return shortDateTime(value)
}

function pluralize(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : (plural ?? `${singular}s`)}`
}

function summarizeStaleReasons(reasons: string[]): string {
  if (reasons.length === 0) return 'No stale signals'
  if (reasons.length === 1) return reasons[0]
  return `${reasons[0]} +${reasons.length - 1} more`
}

interface FactDetailModalProps {
  detail: HindsightFactDetailResponse | undefined
  isOpen: boolean
  onClose: () => void
  onEdit: (fact: HindsightFact) => void
}

function FactDetailModal({ detail, isOpen, onClose, onEdit }: FactDetailModalProps) {
  if (!isOpen || !detail) return null

  const fact = detail.fact
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-memory-detail" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>Fact Detail</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body memory-modal-body">
          <div className="memory-modal-meta-grid">
            <div className="memory-meta-item">
              <span className="memory-meta-label">ID</span>
              <code className="memory-meta-value memory-meta-value-code">{fact.id}</code>
            </div>
            <div className="memory-meta-item">
              <span className="memory-meta-label">Context</span>
              <span className="memory-meta-value">{fact.context}</span>
            </div>
            <div className="memory-meta-item">
              <span className="memory-meta-label">Source</span>
              <span className="memory-meta-value">{fact.source_peer.toUpperCase()}</span>
            </div>
            <div className="memory-meta-item">
              <span className="memory-meta-label">Timestamp</span>
              <span className="memory-meta-value">{dateOnly(fact.timestamp)}</span>
            </div>
            <div className="memory-meta-item">
              <span className="memory-meta-label">Type</span>
              <span className="memory-meta-value">{fact.fact_type || '--'}</span>
            </div>
            <div className="memory-meta-item">
              <span className="memory-meta-label">Document</span>
              <span className="memory-meta-value">{fact.document_id || '--'}</span>
            </div>
          </div>

          <div className="memory-detail-block">
            <h4>Content</h4>
            <pre className="memory-content-block">{fact.content || '--'}</pre>
          </div>

          {fact.entities.length > 0 && (
            <div className="memory-detail-block">
              <h4>Entities</h4>
              <div className="tag-list">
                {fact.entities.map((entity) => (
                  <span key={entity} className="digest-tag">{entity}</span>
                ))}
              </div>
            </div>
          )}

          {fact.stale_reasons.length > 0 && (
            <div className="memory-detail-block">
              <h4>Stale Signals</h4>
              <ul className="memory-stale-list">
                {fact.stale_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </div>
          )}

          {detail.audit_log.length > 0 && (
            <div className="memory-detail-block">
              <h4>Audit Trail</h4>
              <div className="memory-audit-log">
                {detail.audit_log.map((entry, index) => {
                  const data = entry as Record<string, unknown>
                  return (
                    <div key={String(data.id ?? index)} className="memory-audit-item">
                      <span className="ops-meta-label">{String(data.action ?? 'update')}</span>
                      <span className="ops-meta-value">{String(data.timestamp ?? '--')}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={onClose}>Close</button>
          <button
            className="btn btn-primary"
            onClick={() => {
              onEdit(fact)
              onClose()
            }}
          >
            Edit Fact
          </button>
        </div>
      </div>
    </div>
  )
}

interface EditFactModalProps {
  fact: HindsightFact | null
  isSaving: boolean
  onCancel: () => void
  onSave: (factId: string, content: string, context: string) => Promise<void>
}

function EditFactModal({ fact, isSaving, onCancel, onSave }: EditFactModalProps) {
  const form = useForm({
    defaultValues: {
      content: fact?.content ?? '',
      context: fact?.context ?? '',
    },
    onSubmit: async ({ value }) => {
      if (!fact) return
      await onSave(fact.id, value.content, value.context)
    },
  })

  useEffect(() => {
    if (!fact) return
    form.reset({
      content: fact.content,
      context: fact.context,
    })
  }, [fact])

  if (!fact) return null

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal-content modal-memory-edit" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>Edit Fact</h3>
          <button className="modal-close" onClick={onCancel}>×</button>
        </div>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            event.stopPropagation()
            void form.handleSubmit()
          }}
        >
          <div className="modal-body memory-modal-body">
            <form.Field name="context">
              {(field) => (
                <label className="form-field">
                  <span>Context label</span>
                  <input
                    className="text-input"
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                    placeholder="preferences"
                  />
                </label>
              )}
            </form.Field>
            <form.Field name="content">
              {(field) => (
                <label className="form-field">
                  <span>Fact content</span>
                  <textarea
                    className="text-input memory-edit-textarea"
                    value={field.state.value}
                    onChange={(event) => field.handleChange(event.target.value)}
                    rows={8}
                  />
                </label>
              )}
            </form.Field>
          </div>
          <div className="modal-footer">
            <button className="btn" type="button" onClick={onCancel} disabled={isSaving}>Cancel</button>
            <button className="btn btn-primary" type="submit" disabled={isSaving}>
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export function MemoryRoute() {
  const queryClient = useQueryClient()
  const { instance } = useAppState()

  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [contextFilter, setContextFilter] = useState('all')
  const [sourceFilter, setSourceFilter] = useState<HindsightSource>('all')
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [staleOnly, setStaleOnly] = useState(false)
  const [sort, setSort] = useState<'newest' | 'oldest'>('newest')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [detailId, setDetailId] = useState<string | null>(null)
  const [editingFact, setEditingFact] = useState<HindsightFact | null>(null)

  useEffect(() => {
    setPage(0)
    setSelected({})
  }, [search, contextFilter, sourceFilter, fromDate, toDate, staleOnly, sort, instance])

  const effectiveSource: HindsightSource = instance === 'all' ? sourceFilter : instance

  const statsQuery = useQuery({
    queryKey: ['hindsight-stats', effectiveSource],
    queryFn: () => api.getHindsightStats(effectiveSource),
    refetchInterval: 30000,
  })

  const staleQuery = useQuery({
    queryKey: ['hindsight-stale', effectiveSource],
    queryFn: () => api.getHindsightStaleFacts(effectiveSource),
    refetchInterval: 60000,
  })

  const hindsightHealthQuery = useQuery({
    queryKey: ['hindsight-health'],
    queryFn: api.getHindsightHealth,
    refetchInterval: 30000,
  })

  const ingestHealthQuery = useQuery({
    queryKey: ['memory-ingest-health'],
    queryFn: api.getMemoryIngestHealth,
    refetchInterval: 30000,
  })

  const providerStatusQuery = useQuery({
    queryKey: ['provider-status', 'pc'],
    queryFn: () => api.getProviderStatus('pc'),
    refetchInterval: 30000,
  })

  const factsQuery = useQuery({
    queryKey: ['hindsight-facts', search, contextFilter, effectiveSource, fromDate, toDate, staleOnly, sort, page],
    queryFn: () => {
      const params = {
        q: search || undefined,
        context: contextFilter === 'all' ? undefined : contextFilter,
        source: effectiveSource,
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        stale_only: staleOnly,
        sort,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }
      if (search.trim()) {
        return api.searchHindsightFacts({
          q: search.trim(),
          context: params.context,
          source: params.source,
          from_date: params.from_date,
          to_date: params.to_date,
          sort: params.sort,
          limit: PAGE_SIZE,
          offset: page * PAGE_SIZE,
        })
      }
      return api.getHindsightFacts(params)
    },
  })

  const detailQuery = useQuery({
    queryKey: ['hindsight-fact', detailId],
    queryFn: () => api.getHindsightFact(detailId as string),
    enabled: Boolean(detailId),
  })

  const profileQuery = useQuery({
    queryKey: ['memory-profile'],
    queryFn: api.getMemory,
  })

  const configQuery = useQuery({
    queryKey: ['agent-config'],
    queryFn: api.getConfig,
  })

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['hindsight-facts'] }),
      queryClient.invalidateQueries({ queryKey: ['hindsight-fact'] }),
      queryClient.invalidateQueries({ queryKey: ['hindsight-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['hindsight-stale'] }),
      queryClient.invalidateQueries({ queryKey: ['memory-profile'] }),
      queryClient.invalidateQueries({ queryKey: ['agent-config'] }),
    ])
  }

  const updateMutation = useMutation({
    mutationFn: (payload: { factId: string; content: string; context: string }) =>
      api.updateHindsightFact(payload.factId, { content: payload.content, context: payload.context }),
    onSuccess: async () => {
      await refreshAll()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (factId: string) => api.deleteHindsightFact(factId, true),
    onSuccess: async () => {
      await refreshAll()
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => api.bulkDeleteHindsightFacts({ fact_ids: ids, soft_delete: true }),
    onSuccess: async () => {
      setSelected({})
      await refreshAll()
    },
  })

  const personalityMutation = useMutation({
    mutationFn: (personality: string) => api.updateConfig({ personality }),
    onSuccess: async () => {
      await refreshAll()
    },
  })

  const contexts = useMemo(() => {
    const keys = Object.keys(statsQuery.data?.facts_per_context ?? {})
    return ['all', ...keys]
  }, [statsQuery.data?.facts_per_context])

  const hindsightProvider = useMemo<ProviderStatusItem | null>(() => {
    const providers = providerStatusQuery.data?.providers ?? []
    for (const provider of providers) {
      if (provider.primary_flows.some((flow) => flow.flow === 'Hindsight Memory')) {
        return provider
      }
    }
    return null
  }, [providerStatusQuery.data?.providers])

  const memoryHealth = useMemo(() => {
    if (hindsightHealthQuery.isError) {
      return {
        tone: 'error' as const,
        title: 'Memory offline',
        message: 'Mission Control could not reach the Hindsight API.',
      }
    }

    const hindsightHealth = hindsightHealthQuery.data
    const ingestHealth = ingestHealthQuery.data
    const provider = hindsightProvider
    const providerStatus = provider?.status ?? 'unknown'

    if (hindsightHealth && !hindsightHealth.ok) {
      return {
        tone: 'error' as const,
        title: 'Memory offline',
        message: hindsightHealth.error || 'Hindsight API is not reachable from Mission Control.',
      }
    }

    const degradedReasons: string[] = []
    if (provider && providerStatus !== 'active') {
      degradedReasons.push(
        `${provider.name} is ${providerStatus}${provider.status_reason ? `: ${provider.status_reason}` : ''}`,
      )
    }
    if (ingestHealth && !ingestHealth.ok) {
      degradedReasons.push(ingestHealth.error || 'memory ingest writes are failing')
    }

    if (degradedReasons.length > 0) {
      return {
        tone: 'warning' as const,
        title: 'Memory degraded',
        message: `Recall should still work, but retain/reflect may fail. ${degradedReasons.join(' ')}`.trim(),
      }
    }

    if (hindsightHealth?.ok) {
      return {
        tone: 'ok' as const,
        title: 'Memory healthy',
        message: provider
          ? `Hindsight API is reachable and memory backend is ${provider.name}${provider.current_model ? ` (${provider.current_model})` : ''}.`
          : 'Hindsight API is reachable and memory read/write paths look healthy.',
      }
    }

    return {
      tone: 'warning' as const,
      title: 'Memory status pending',
      message: 'Waiting for memory health checks to complete.',
    }
  }, [hindsightHealthQuery.data, hindsightHealthQuery.isError, ingestHealthQuery.data, hindsightProvider])

  const facts = factsQuery.data?.items ?? []
  const selectedIds = Object.keys(selected).filter((id) => selected[id])
  const activeFilterSummary = useMemo(() => {
    const filters: string[] = []
    if (search) filters.push(`query "${search}"`)
    if (contextFilter !== 'all') filters.push(`context ${contextFilter}`)
    if (effectiveSource !== 'all') filters.push(`source ${effectiveSource.toUpperCase()}`)
    if (fromDate) filters.push(`from ${fromDate}`)
    if (toDate) filters.push(`to ${toDate}`)
    if (staleOnly) filters.push('stale only')
    if (sort === 'oldest') filters.push('oldest first')
    return filters
  }, [search, contextFilter, effectiveSource, fromDate, toDate, staleOnly, sort])

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'select',
        header: () => {
          const allSelected = facts.length > 0 && facts.every((fact) => selected[fact.id])
          return (
            <input
              type="checkbox"
              checked={allSelected}
              onChange={(event) => {
                const checked = event.target.checked
                setSelected((current) => {
                  const next = { ...current }
                  for (const fact of facts) {
                    next[fact.id] = checked
                  }
                  return next
                })
              }}
            />
          )
        },
        cell: (info) => {
          const fact = info.row.original
          return (
            <input
              type="checkbox"
              checked={Boolean(selected[fact.id])}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) => {
                const checked = event.target.checked
                setSelected((current) => ({
                  ...current,
                  [fact.id]: checked,
                }))
              }}
            />
          )
        },
      }),
      columnHelper.accessor('timestamp', {
        header: 'Time',
        cell: (info) => {
          const fact = info.row.original
          return (
            <div className="memory-time-cell">
              <span className="memory-time-value">{dateOnly(info.getValue())}</span>
              <span className="memory-time-meta">{fact.updated_at ? 'updated' : 'captured'}</span>
            </div>
          )
        },
      }),
      columnHelper.accessor('content', {
        header: 'Fact',
        cell: (info) => {
          const row = info.row.original
          return (
            <div className="memory-content-cell">
              <div className="memory-fact-meta">
                <span className="memory-context-chip">{row.context}</span>
                <span className={`instance-badge instance-${row.source_peer}`}>{row.source_peer.toUpperCase()}</span>
                {row.fact_type && <span className="memory-fact-type">{row.fact_type}</span>}
                {row.entities.length > 0 && (
                  <span className="memory-fact-inline-note">{pluralize(row.entities.length, 'entity')}</span>
                )}
                {row.document_id && <span className="memory-fact-inline-note">doc {row.document_id}</span>}
              </div>
              <div className="memory-content-preview memory-content-preview-expanded">{info.getValue()}</div>
              <div className="memory-fact-subline">
                <span>{row.updated_at ? `Updated ${dateOnly(row.updated_at)}` : `Captured ${dateOnly(row.timestamp)}`}</span>
                <span className="memory-row-hint">Open row for detail + audit trail</span>
              </div>
              {row.stale_reasons.length > 0 && (
                <span className="memory-stale-flag">
                  ⚠ {summarizeStaleReasons(row.stale_reasons)}
                </span>
              )}
            </div>
          )
        },
      }),
      columnHelper.display({
        id: 'status',
        header: 'Status',
        cell: (info) => {
          const fact = info.row.original
          return (
            <div className="memory-status-cell">
              <span className={`memory-status-pill ${fact.stale_reasons.length > 0 ? 'is-warning' : 'is-ok'}`}>
                {fact.stale_reasons.length > 0 ? 'Needs review' : 'Current'}
              </span>
              <span className="memory-status-meta">
                {summarizeStaleReasons(fact.stale_reasons)}
              </span>
            </div>
          )
        },
      }),
      columnHelper.display({
        id: 'actions',
        header: 'Actions',
        cell: (info) => {
          const fact = info.row.original
          return (
            <div className="memory-actions-cell">
              <button
                className="action-btn"
                onClick={(event) => {
                  event.stopPropagation()
                  setDetailId(fact.id)
                }}
              >
                Open
              </button>
              <button
                className="action-btn"
                onClick={(event) => {
                  event.stopPropagation()
                  setEditingFact(fact)
                }}
              >
                Edit
              </button>
              <button
                className="action-btn action-btn-danger"
                onClick={(event) => {
                  event.stopPropagation()
                  if (!window.confirm('Soft-delete this fact?')) return
                  deleteMutation.mutate(fact.id)
                }}
              >
                Delete
              </button>
            </div>
          )
        },
      }),
    ],
    [facts, selected, deleteMutation],
  )

  const table = useReactTable({
    data: facts,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const total = factsQuery.data?.total ?? 0
  const hasMore = factsQuery.data?.has_more ?? false
  const pageStart = total === 0 ? 0 : page * PAGE_SIZE + 1
  const pageEnd = page * PAGE_SIZE + facts.length

  return (
    <div id="memory-view" className="view memory-view">
      <div className="page-header page-header-main">
        <div>
          <h2 className="page-title">Hindsight Memory Bank</h2>
          <p className="page-subtitle">Fact management, stale review, profile visibility, and personality controls</p>
        </div>
        <div className="cron-stats">
          <div className="stat-pill"><span className="stat-value">{statsQuery.data?.total_facts ?? 0}</span><span className="stat-label">Facts</span></div>
          <div className="stat-pill stat-pill-warning"><span className="stat-value">{statsQuery.data?.stale_candidates ?? 0}</span><span className="stat-label">Stale</span></div>
          <div className="stat-pill"><span className="stat-value">{formatBytes(statsQuery.data?.storage_estimate_bytes ?? 0)}</span><span className="stat-label">Storage</span></div>
          <div className="stat-pill"><span className="stat-value">{dateOnly(statsQuery.data?.last_sync_timestamp)}</span><span className="stat-label">Last PI Sync</span></div>
        </div>
      </div>

      <div className={`alert memory-health-banner memory-health-${memoryHealth.tone}`}>
        <span className="alert-icon">
          {memoryHealth.tone === 'error' ? '⛔' : memoryHealth.tone === 'warning' ? '⚠' : '✓'}
        </span>
        <div className="alert-message">
          <strong>{memoryHealth.title}.</strong> {memoryHealth.message}
        </div>
      </div>

      <section className="section memory-top-grid">
        <div className="memory-filter-panel">
          <h3 className="section-title">Fact Browser</h3>
          <div className="memory-filter-grid">
            <label className="form-field">
              <span>Search</span>
              <div className="memory-search-row">
                <input
                  className="text-input"
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                  placeholder="Find facts by content"
                />
                <button className="btn btn-primary" onClick={() => setSearch(searchInput.trim())}>Apply</button>
              </div>
            </label>

            <label className="form-field">
              <span>Context</span>
              <select className="text-input" value={contextFilter} onChange={(event) => setContextFilter(event.target.value)}>
                {contexts.map((context) => (
                  <option key={context} value={context}>{context === 'all' ? 'All contexts' : context}</option>
                ))}
              </select>
            </label>

            <label className="form-field">
              <span>Source</span>
              <select
                className="text-input"
                value={sourceFilter}
                onChange={(event) => setSourceFilter(event.target.value as HindsightSource)}
                disabled={instance !== 'all'}
              >
                <option value="all">All</option>
                <option value="pc">PC</option>
                <option value="pi">PI</option>
              </select>
            </label>

            <label className="form-field">
              <span>From date</span>
              <input className="text-input" type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
            </label>

            <label className="form-field">
              <span>To date</span>
              <input className="text-input" type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
            </label>

            <label className="form-field">
              <span>Sort</span>
              <select
                className="text-input"
                value={sort}
                onChange={(event) => setSort(event.target.value as 'newest' | 'oldest')}
              >
                <option value="newest">Newest first</option>
                <option value="oldest">Oldest first</option>
              </select>
            </label>

            <label className="memory-toggle">
              <input type="checkbox" checked={staleOnly} onChange={(event) => setStaleOnly(event.target.checked)} />
              <span>Review stale facts only</span>
            </label>
          </div>
        </div>

        <div className="memory-profile-panel">
          <h3 className="section-title">Profile & Personality</h3>
          <div className="memory-profile-meta">
            <div className="ops-meta-row">
              <span className="ops-meta-label">Instance context</span>
              <span className="ops-meta-value">{instance.toUpperCase()}</span>
            </div>
            <div className="ops-meta-row">
              <span className="ops-meta-label">Current personality</span>
              <span className="ops-meta-value">{configQuery.data?.personality ?? '--'}</span>
            </div>
            <div className="ops-meta-row">
              <span className="ops-meta-label">Visible profile memories</span>
              <span className="ops-meta-value">{profileQuery.data?.entries.length ?? 0}</span>
            </div>
          </div>

          <div className="memory-personality-row">
            {(profileQuery.data?.personality.available ?? []).map((name) => (
              <button
                key={name}
                className={`filter-btn ${configQuery.data?.personality === name ? 'active' : ''}`}
                onClick={() => personalityMutation.mutate(name)}
                disabled={personalityMutation.isPending}
              >
                {name}
              </button>
            ))}
          </div>

          <div className="memory-profile-list">
            {(profileQuery.data?.entries ?? []).slice(0, 5).map((entry) => (
              <div className="memory-profile-item" key={entry.key}>
                <span className="ops-meta-label">{entry.key}</span>
                <span className="ops-meta-value">{entry.value}</span>
              </div>
            ))}
            {!profileQuery.data?.entries.length && <p className="empty-text">No profile entries available</p>}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="memory-table-header">
          <div>
            <h3 className="section-title">Facts</h3>
            <p className="memory-table-description">
              Each row is one retained memory fact. Use filters to narrow the bank, click a row to inspect the full fact and audit trail, or use actions for direct edits.
            </p>
          </div>
          <div className="memory-table-actions">
            <span className="inline-note">Showing {pageStart}-{pageEnd} of {total}</span>
            {activeFilterSummary.length > 0 && (
              <span className="inline-note">Filtered by {activeFilterSummary.join(' · ')}</span>
            )}
            {selectedIds.length > 0 && (
              <span className="inline-note">{pluralize(selectedIds.length, 'fact')} selected</span>
            )}
            {selectedIds.length > 0 && (
              <button
                className="btn btn-primary"
                onClick={() => {
                  if (!window.confirm(`Soft-delete ${selectedIds.length} selected facts?`)) return
                  bulkDeleteMutation.mutate(selectedIds)
                }}
                disabled={bulkDeleteMutation.isPending}
              >
                Delete Selected ({selectedIds.length})
              </button>
            )}
          </div>
        </div>

        {factsQuery.isLoading ? (
          <div className="state-container state-loading">
            <div className="spinner" />
            <p>Loading memory facts...</p>
          </div>
        ) : factsQuery.isError ? (
          <div className="state-container state-error">
            <h3>Failed to load facts</h3>
            <button className="btn btn-primary" onClick={() => factsQuery.refetch()}>Retry</button>
          </div>
        ) : (
          <div className="memory-table-container sessions-table-container">
            <table className="data-table memory-table">
              <thead>
                {table.getHeaderGroups().map((headerGroup) => (
                  <tr key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <th key={header.id}>
                        {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="memory-row" onClick={() => setDetailId(row.original.id)}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {facts.length === 0 && <p className="empty-text">No facts found for current filters.</p>}
          </div>
        )}

        <div className="memory-pagination">
          <button className="btn" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0}>Previous</button>
          <span className="inline-note">Page {page + 1}</span>
          <button className="btn" onClick={() => setPage((current) => current + 1)} disabled={!hasMore}>Next</button>
        </div>
      </section>

      <section className="section">
        <div className="memory-stale-header">
          <h3 className="section-title">Stale Review Queue</h3>
          <span className="inline-note">{staleQuery.data?.total ?? 0} candidates</span>
        </div>
        <div className="memory-stale-grid">
          {(staleQuery.data?.items ?? []).slice(0, 6).map((fact) => (
            <article key={fact.id} className="memory-stale-card" onClick={() => setDetailId(fact.id)}>
              <div className="memory-stale-card-head">
                <span className="memory-context-chip">{fact.context}</span>
                <span className={`instance-badge instance-${fact.source_peer}`}>{fact.source_peer.toUpperCase()}</span>
              </div>
              <p className="memory-content-preview">{fact.content}</p>
              <ul className="memory-stale-list">
                {fact.stale_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </article>
          ))}
          {!staleQuery.data?.items.length && <p className="empty-text">No stale candidates detected.</p>}
        </div>
      </section>

      <FactDetailModal
        detail={detailQuery.data}
        isOpen={Boolean(detailId)}
        onClose={() => setDetailId(null)}
        onEdit={(fact) => setEditingFact(fact)}
      />

      <EditFactModal
        fact={editingFact}
        isSaving={updateMutation.isPending}
        onCancel={() => setEditingFact(null)}
        onSave={async (factId, content, context) => {
          await updateMutation.mutateAsync({ factId, content, context })
          setEditingFact(null)
        }}
      />
    </div>
  )
}
