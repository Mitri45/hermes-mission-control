import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { api } from '../lib/api'
import { useAppState } from '../lib/state'
import type { ProviderPanelStatus, ProviderStatusItem } from '../types'

const columnHelper = createColumnHelper<ProviderStatusItem>()

function ProviderStatusBadge({ status }: { status: ProviderPanelStatus }) {
  const normalized = status.toLowerCase()
  let className = 'status-badge'
  if (normalized === 'active') className += ' status-active'
  else if (normalized === 'off-limits') className += ' status-off-limits'
  else if (normalized === 'exhausted') className += ' status-exhausted'
  else if (normalized === 'misconfigured') className += ' status-misconfigured'
  else className += ' status-unknown'

  return (
    <span className={className}>
      <span className="status-indicator-inline">●</span>
      {status.toUpperCase()}
    </span>
  )
}

export function ProvidersRoute() {
  const { instance } = useAppState()
  const providersQuery = useQuery({
    queryKey: ['provider-status', instance],
    queryFn: () => api.getProviderStatus(instance),
    refetchInterval: 30000,
  })

  const columns = useMemo(
    () => [
      columnHelper.accessor('name', {
        header: 'Provider',
        cell: (info) => (
          <div className="provider-name-cell">
            <div className="provider-name">{info.getValue()}</div>
            <div className="provider-id">{info.row.original.provider}</div>
          </div>
        ),
      }),
      columnHelper.accessor('status', {
        header: 'Status',
        cell: (info) => {
          const row = info.row.original
          return (
            <div className="provider-status-cell">
              <ProviderStatusBadge status={info.getValue()} />
              <span className="provider-reason">{row.status_reason ?? '--'}</span>
            </div>
          )
        },
      }),
      columnHelper.accessor('current_model', {
        header: 'Model',
        cell: (info) => <span className="provider-model">{info.getValue() || '--'}</span>,
      }),
      columnHelper.accessor('base_url', {
        header: 'Endpoint',
        cell: (info) => (
          <span className="provider-endpoint" title={info.getValue() || ''}>
            {info.getValue() || '--'}
          </span>
        ),
      }),
      columnHelper.accessor('primary_flows', {
        header: 'Primary Flows',
        cell: (info) => {
          const flows = info.getValue()
          if (!flows.length) return <span className="provider-empty">--</span>
          return (
            <div className="provider-flows">
              {flows.map((flow) => (
                <div key={`${flow.flow}-${flow.instance}`} className="provider-flow-chip">
                  <span className="flow-name">{flow.flow}</span>
                  <span className="flow-instance">{flow.instance.toUpperCase()}</span>
                </div>
              ))}
            </div>
          )
        },
      }),
      columnHelper.accessor('last_error', {
        header: 'Last Error',
        cell: (info) => <span className="provider-last-error">{info.getValue() || '--'}</span>,
      }),
    ],
    [],
  )

  const table = useReactTable({
    data: providersQuery.data?.providers ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  if (providersQuery.isLoading) {
    return (
      <div id="loading-state" className="state-container state-loading">
        <div className="spinner" />
        <p>Loading provider visibility...</p>
      </div>
    )
  }

  if (providersQuery.isError) {
    return (
      <div id="error-state" className="state-container state-error">
        <h3>Failed to load provider status</h3>
        <p id="error-message">Unable to read provider visibility data</p>
        <button className="btn btn-primary" onClick={() => providersQuery.refetch()} id="retry-btn">
          Retry
        </button>
      </div>
    )
  }

  const summary = providersQuery.data?.summary
  const providers = providersQuery.data?.providers ?? []

  return (
    <div id="providers-view" className="view">
      <div className="page-header page-header-main">
        <div>
          <h2 className="page-title">LLM Provider Visibility</h2>
          <p className="page-subtitle">Provider health, key status, and flow-level model usage</p>
        </div>
        <div className="cron-stats">
          <div className="stat-pill"><span className="stat-value">{summary?.total ?? providers.length}</span><span className="stat-label">Total</span></div>
          <div className="stat-pill stat-pill-success"><span className="stat-value">{summary?.active ?? 0}</span><span className="stat-label">Active</span></div>
          <div className="stat-pill stat-pill-warning"><span className="stat-value">{summary?.off_limits ?? 0}</span><span className="stat-label">Off-Limits</span></div>
          <div className="stat-pill stat-pill-error"><span className="stat-value">{summary?.exhausted ?? 0}</span><span className="stat-label">Exhausted</span></div>
        </div>
      </div>

      {providers.length === 0 ? (
        <div id="empty-state" className="state-container state-empty">
          <h3>No providers discovered</h3>
          <p>No provider configuration was found for instance filter: {instance.toUpperCase()}</p>
        </div>
      ) : (
        <section className="section">
          <h3 className="section-title">Provider Matrix</h3>
          <div className="providers-table-container sessions-table-container">
            <table className="data-table providers-table">
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
                  <tr key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <td key={cell.id}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
