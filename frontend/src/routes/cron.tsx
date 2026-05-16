import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createColumnHelper, flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type SortingState } from '@tanstack/react-table'
import { api } from '../lib/api'
import { shortDateTime, formatDuration } from '../lib/format'
import { useAppState } from '../lib/state'
import type { ActionInstance, CronJob, InstanceFilter } from '../types'
import { useForm } from '@tanstack/react-form'

const columnHelper = createColumnHelper<CronJob>()

type JobStatus = 'active' | 'scheduled' | 'paused' | 'running' | 'error'
type ToastVariant = 'success' | 'error' | 'warning' | 'info'
const TOAST_TIMEOUT_MS = 3500
const TOAST_CONTAINER_ID = 'toast-container'
const FALLBACK_TOAST_CONTAINER_ID = 'toast-container-fallback'
const CRON_FIELD_TOKEN_PATTERN = /^[\d/*,\-]+$/
const CRON_FIELD_COUNT = 5

function getToastContainer(): HTMLElement {
  const primary = document.getElementById(TOAST_CONTAINER_ID)
  if (primary) return primary

  const fallback = document.getElementById(FALLBACK_TOAST_CONTAINER_ID)
  if (fallback) return fallback

  const created = document.createElement('div')
  created.id = FALLBACK_TOAST_CONTAINER_ID
  created.className = 'toast-container'
  document.body.appendChild(created)
  return created
}

function validateCronScheduleInput(value: string): string | null {
  const schedule = value.trim()
  if (!schedule) return 'Schedule is required'

  const fields = schedule.split(/\s+/)
  if (fields.length !== CRON_FIELD_COUNT) {
    return 'Cron must have exactly 5 fields'
  }
  if (!fields.every((field) => CRON_FIELD_TOKEN_PATTERN.test(field))) {
    return 'Cron fields can use digits, *, /, -, and commas'
  }

  return null
}

function notify(message: string, variant: ToastVariant = 'info') {
  const container = getToastContainer()

  const toast = document.createElement('div')
  toast.className = `toast toast-${variant}`
  toast.textContent = message
  container.appendChild(toast)

  window.setTimeout(() => {
    toast.remove()
  }, TOAST_TIMEOUT_MS)
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return 'Unexpected error'
}

function StatusBadge({ status, enabled }: { status: string; enabled: boolean }) {
  const normalized = status.toLowerCase() as JobStatus
  let indicator = '●'
  let className = 'status-badge'

  if (!enabled) {
    className += ' status-disabled'
  } else if (normalized === 'active' || normalized === 'scheduled') {
    className += ' status-active'
  } else if (normalized === 'running') {
    className += ' status-running'
  } else if (normalized === 'paused') {
    className += ' status-paused'
  } else if (normalized === 'error') {
    className += ' status-error'
  }

  return (
    <span className={className}>
      <span className="status-indicator-inline">{indicator}</span>
      {status.toUpperCase()}
    </span>
  )
}

function ResultBadge({ result }: { result?: string }) {
  if (!result) return <span className="result-badge result-none">--</span>

  const normalized = result.toLowerCase()
  let className = 'result-badge'

  if (normalized === 'success') {
    className += ' result-success'
  } else if (normalized === 'failed') {
    className += ' result-failed'
  } else if (normalized === 'triggered') {
    className += ' result-triggered'
  }

  return <span className={className}>{result.toUpperCase()}</span>
}

function InstanceBadge({ instance }: { instance: string }) {
  const normalized = instance.toLowerCase()
  return (
    <span className={`instance-badge instance-${normalized}`}>
      {instance.toUpperCase()}
    </span>
  )
}

function HealthIndicator({
  failureCount,
  lastResult,
}: {
  failureCount: number
  lastResult?: string
}) {
  let state: 'healthy' | 'warning' | 'critical' = 'healthy'

  if (lastResult === 'failed') {
    state = failureCount >= 3 ? 'critical' : 'warning'
  }

  return (
    <span className={`health-indicator health-${state}`} title={`${failureCount} consecutive failures`}>
      {state === 'healthy' ? '◉' : state === 'warning' ? '◈' : '◉'}
    </span>
  )
}

interface JobActionsProps {
  job: CronJob
  actionInstance: ActionInstance | null
  onRun: (id: string, actionInstance: ActionInstance) => void
  onPause: (id: string, actionInstance: ActionInstance) => void
  onResume: (id: string, actionInstance: ActionInstance) => void
  onRetry: (id: string, actionInstance: ActionInstance) => void
  onEdit: (job: CronJob) => void
  isPending: boolean
}

function JobActions({ job, actionInstance, onRun, onPause, onResume, onRetry, onEdit, isPending }: JobActionsProps) {
  const isRunning = job.status === 'running'
  const isPaused = job.status === 'paused'
  const isFailed = job.last_result === 'failed'
  const actionBlocked = actionInstance === null
  const isDisabled = isPending || isRunning || actionBlocked
  const actionTarget = actionInstance ? actionInstance.toUpperCase() : null
  const blockedTitle = 'Select PC or PI view to run this action explicitly'

  return (
    <div className="job-actions">
      {actionTarget ? (
        <span className="action-instance-chip">{actionTarget}</span>
      ) : (
        <span className="action-instance-chip action-instance-chip-blocked">--</span>
      )}
      <button
        className="action-btn action-run"
        onClick={() => actionInstance && onRun(job.id, actionInstance)}
        disabled={isDisabled}
        title={actionTarget ? `Run now on ${actionTarget}` : blockedTitle}
      >
        ▶
      </button>

      {isPaused ? (
        <button
          className="action-btn action-resume"
          onClick={() => actionInstance && onResume(job.id, actionInstance)}
          disabled={isPending || actionBlocked}
          title={actionTarget ? `Resume on ${actionTarget}` : blockedTitle}
        >
          ▶|
        </button>
      ) : (
        <button
          className="action-btn action-pause"
          onClick={() => actionInstance && onPause(job.id, actionInstance)}
          disabled={isDisabled}
          title={actionTarget ? `Pause on ${actionTarget}` : blockedTitle}
        >
          ■
        </button>
      )}

      {isFailed && (
        <button
          className="action-btn action-retry"
          onClick={() => actionInstance && onRetry(job.id, actionInstance)}
          disabled={isPending || actionBlocked}
          title={actionTarget ? `Retry failed run on ${actionTarget}` : blockedTitle}
        >
          ↻
        </button>
      )}

      <button
        className="action-btn action-edit"
        onClick={() => onEdit(job)}
        disabled={isPending}
        title="Edit settings"
      >
        ✎
      </button>
    </div>
  )
}

interface EditJobModalProps {
  job: CronJob | null
  isOpen: boolean
  onClose: () => void
  onSave: (id: string, data: { name: string; schedule: string; enabled: boolean; target: string; instance: string }) => void
  isPending: boolean
}

function EditJobModal({ job, isOpen, onClose, onSave, isPending }: EditJobModalProps) {
  const [scheduleError, setScheduleError] = useState<string | null>(() =>
    validateCronScheduleInput(job?.schedule ?? ''),
  )

  const form = useForm({
    defaultValues: {
      name: job?.name ?? '',
      schedule: job?.schedule ?? '',
      enabled: job?.enabled ?? true,
      target: job?.target ?? '',
      instance: job?.instance ?? 'pc',
    },
    onSubmit: async ({ value }) => {
      if (job) {
        const validationError = validateCronScheduleInput(value.schedule)
        if (validationError) {
          setScheduleError(validationError)
          return
        }
        onSave(job.id, value)
      }
    },
  })

  if (!isOpen || !job) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Edit Job: {job.name}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            form.handleSubmit()
          }}
          className="modal-body"
        >
          <div className="form-row">
            <form.Field
              name="name"
              children={(field) => (
                <div className="form-field">
                  <label htmlFor={field.name}>Name</label>
                  <input
                    id={field.name}
                    name={field.name}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                    className="text-input"
                    disabled={isPending}
                  />
                </div>
              )}
            />
          </div>

          <div className="form-row">
            <form.Field
              name="schedule"
              children={(field) => (
                <div className="form-field">
                  <label htmlFor={field.name}>Schedule (Cron)</label>
                  <input
                    id={field.name}
                    name={field.name}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => {
                      const nextValue = e.target.value
                      field.handleChange(nextValue)
                      setScheduleError(validateCronScheduleInput(nextValue))
                    }}
                    className={`text-input ${scheduleError ? 'text-input-error' : ''}`}
                    disabled={isPending}
                    placeholder="*/30 * * * *"
                    aria-invalid={scheduleError ? true : undefined}
                  />
                  {scheduleError ? <span className="form-error">{scheduleError}</span> : null}
                </div>
              )}
            />
          </div>

          <div className="form-row">
            <form.Field
              name="target"
              children={(field) => (
                <div className="form-field">
                  <label htmlFor={field.name}>Target</label>
                  <input
                    id={field.name}
                    name={field.name}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                    className="text-input"
                    disabled={isPending}
                    placeholder="telegram, local, git"
                  />
                </div>
              )}
            />
          </div>

          <div className="form-row">
            <form.Field
              name="instance"
              children={(field) => (
                <div className="form-field">
                  <label htmlFor={field.name}>Instance</label>
                  <select
                    id={field.name}
                    name={field.name}
                    value={field.state.value}
                    onBlur={field.handleBlur}
                    onChange={(e) => field.handleChange(e.target.value)}
                    className="text-input"
                    disabled={isPending}
                  >
                    <option value="pc">PC</option>
                    <option value="pi">Pi</option>
                    <option value="both">Both</option>
                  </select>
                </div>
              )}
            />
          </div>

          <div className="form-row">
            <form.Field
              name="enabled"
              children={(field) => (
                <div className="form-field form-field-checkbox">
                  <label>
                    <input
                      type="checkbox"
                      name={field.name}
                      checked={field.state.value}
                      onBlur={field.handleBlur}
                      onChange={(e) => field.handleChange(e.target.checked)}
                      disabled={isPending}
                    />
                    Enabled
                  </label>
                </div>
              )}
            />
          </div>

          <div className="modal-footer">
            <button type="button" className="btn" onClick={onClose} disabled={isPending}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={isPending || !!scheduleError}>
              {isPending ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

interface ErrorDetailModalProps {
  job: CronJob | null
  isOpen: boolean
  onClose: () => void
}

function ErrorDetailModal({ job, isOpen, onClose }: ErrorDetailModalProps) {
  if (!isOpen || !job) return null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content modal-error" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>❌ Error Details: {job.name}</h3>
          <button className="modal-close" onClick={onClose}>×</button>
        </div>

        <div className="modal-body">
          <div className="error-section">
            <h4>Failure Reason</h4>
            <p className="error-reason">{job.failure_reason || 'No failure reason recorded'}</p>
          </div>

          <div className="error-section">
            <h4>Job Details</h4>
            <div className="error-details">
              <div><strong>Job ID:</strong> {job.id}</div>
              <div><strong>Last Run:</strong> {shortDateTime(job.last_run)}</div>
              <div><strong>Runtime:</strong> {formatDuration(job.runtime_seconds)}</div>
              <div><strong>Consecutive Failures:</strong> {job.failure_count}</div>
              <div><strong>Instance:</strong> {job.instance.toUpperCase()}</div>
            </div>
          </div>

          <div className="error-section">
            <h4>Actions</h4>
            <div className="error-actions">
              <a href={`/api/cron/${job.id}/logs`} className="btn btn-primary" target="_blank" rel="noopener noreferrer">
                View Logs
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export function CronRoute() {
  const { instance } = useAppState()
  const queryClient = useQueryClient()
  const [sorting, setSorting] = useState<SortingState>([{ id: 'status', desc: false }])
  const [editingJob, setEditingJob] = useState<CronJob | null>(null)
  const [errorJob, setErrorJob] = useState<CronJob | null>(null)

  // Queries
  const cronQuery = useQuery({
    queryKey: ['cron-table', instance],
    queryFn: () => api.getCron(instance),
    refetchInterval: 30000,
  })

  const invalidateCronViews = () => {
    queryClient.invalidateQueries({ queryKey: ['cron-table'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard-cron'] })
    queryClient.invalidateQueries({ queryKey: ['nav-cron-badge'] })
  }

  // Mutations
  const pauseMutation = useMutation({
    mutationFn: ({ id, actionInstance }: { id: string; actionInstance: ActionInstance }) =>
      api.pauseJob(id, actionInstance),
    onSuccess: (_data, vars) => {
      invalidateCronViews()
      notify(`Paused ${vars.id} on ${vars.actionInstance.toUpperCase()}`, 'success')
    },
    onError: (error) => {
      notify(`Pause failed: ${toErrorMessage(error)}`, 'error')
    },
  })

  const resumeMutation = useMutation({
    mutationFn: ({ id, actionInstance }: { id: string; actionInstance: ActionInstance }) =>
      api.resumeJob(id, actionInstance),
    onSuccess: (_data, vars) => {
      invalidateCronViews()
      notify(`Resumed ${vars.id} on ${vars.actionInstance.toUpperCase()}`, 'success')
    },
    onError: (error) => {
      notify(`Resume failed: ${toErrorMessage(error)}`, 'error')
    },
  })

  const runMutation = useMutation({
    mutationFn: ({ id, actionInstance }: { id: string; actionInstance: ActionInstance }) =>
      api.runJob(id, actionInstance),
    onSuccess: (_data, vars) => {
      invalidateCronViews()
      notify(`Triggered ${vars.id} on ${vars.actionInstance.toUpperCase()}`, 'success')
    },
    onError: (error) => {
      notify(`Run failed: ${toErrorMessage(error)}`, 'error')
    },
  })

  const retryMutation = useMutation({
    mutationFn: ({ id, actionInstance }: { id: string; actionInstance: ActionInstance }) =>
      api.retryJob(id, actionInstance),
    onSuccess: (_data, vars) => {
      invalidateCronViews()
      notify(`Retry started for ${vars.id} on ${vars.actionInstance.toUpperCase()}`, 'success')
    },
    onError: (error) => {
      notify(`Retry failed: ${toErrorMessage(error)}`, 'error')
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof api.updateJob>[1] }) =>
      api.updateJob(id, data),
    onSuccess: () => {
      invalidateCronViews()
      setEditingJob(null)
      notify('Cron job settings updated', 'success')
    },
    onError: (error) => {
      notify(`Update failed: ${toErrorMessage(error)}`, 'error')
    },
  })

  const isPending =
    pauseMutation.isPending ||
    resumeMutation.isPending ||
    runMutation.isPending ||
    retryMutation.isPending ||
    updateMutation.isPending

  const rows = cronQuery.data?.jobs ?? []

  // Calculate summary stats
  const stats = useMemo(() => {
    const total = rows.length
    const scheduled = rows.filter((j) => (j.status === 'active' || j.status === 'scheduled') && j.enabled).length
    const paused = rows.filter((j) => j.status === 'paused' || !j.enabled).length
    const failed = rows.filter((j) => j.last_result === 'failed').length
    const unhealthy = rows.filter((j) => j.failure_count >= 3 || j.status === 'error').length
    return { total, scheduled, paused, failed, unhealthy }
  }, [rows])

  const getActionInstance = (job: CronJob): ActionInstance | null => {
    if (instance === 'pc' || instance === 'pi') return instance
    if (job.instance === 'pc' || job.instance === 'pi') return job.instance
    return null
  }

  const columns = [
      columnHelper.accessor('status', {
        header: 'Health',
        cell: (info) => {
          const job = info.row.original
          return <HealthIndicator failureCount={job.failure_count} lastResult={job.last_result} />
        },
      }),
      columnHelper.accessor('name', {
        header: 'Name',
        cell: (info) => (
          <div className="job-name-cell">
            <span className="job-name">{info.getValue()}</span>
            <span className="job-id">{info.row.original.id}</span>
          </div>
        ),
      }),
      columnHelper.accessor('instance', {
        header: 'Instance',
        cell: (info) => <InstanceBadge instance={info.getValue()} />,
      }),
      columnHelper.accessor('target', {
        header: 'Target',
        cell: (info) => <span className="target-badge">{info.getValue()}</span>,
      }),
      columnHelper.accessor('schedule', {
        header: 'Schedule',
        cell: (info) => <code className="cron-schedule">{info.getValue()}</code>,
      }),
      columnHelper.accessor('next_run', {
        header: 'Next Run',
        cell: (info) => <span className="timestamp">{shortDateTime(info.getValue())}</span>,
      }),
      columnHelper.accessor('last_run', {
        header: 'Last Run',
        cell: (info) => <span className="timestamp">{shortDateTime(info.getValue())}</span>,
      }),
      columnHelper.accessor('runtime_seconds', {
        header: 'Runtime',
        cell: (info) => <span className="duration">{formatDuration(info.getValue())}</span>,
      }),
      columnHelper.accessor('status', {
        header: 'Status',
        cell: (info) => {
          const job = info.row.original
          return <StatusBadge status={job.status} enabled={job.enabled} />
        },
      }),
      columnHelper.accessor('last_result', {
        header: 'Result',
        cell: (info) => {
          const result = info.getValue()
          const job = info.row.original
          if (result === 'failed' && job.failure_reason) {
            return (
              <button
                className="result-failed-link"
                onClick={() => setErrorJob(job)}
                title={job.failure_reason}
              >
                <ResultBadge result={result} />
              </button>
            )
          }
          return <ResultBadge result={result} />
        },
      }),
      columnHelper.display({
        id: 'actions',
        header: 'Actions',
        cell: (info) => (
          <JobActions
            job={info.row.original}
            actionInstance={getActionInstance(info.row.original)}
            onRun={(id, actionInstance) => runMutation.mutate({ id, actionInstance })}
            onPause={(id, actionInstance) => pauseMutation.mutate({ id, actionInstance })}
            onResume={(id, actionInstance) => resumeMutation.mutate({ id, actionInstance })}
            onRetry={(id, actionInstance) => retryMutation.mutate({ id, actionInstance })}
            onEdit={(job) => setEditingJob(job)}
            isPending={isPending}
          />
        ),
      }),
    ]

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  const instanceLabel: Record<InstanceFilter, string> = {
    all: 'All Instances',
    pc: 'PC Only',
    pi: 'Pi Only',
  }

  return (
    <div id="cron-view" className="view">
      <div className="page-header">
        <div className="page-header-main">
          <div>
            <h2 className="page-title">Cron Jobs</h2>
            <p className="page-subtitle">Manage scheduled jobs across instances • {instanceLabel[instance]}</p>
          </div>
          <div className="cron-stats">
            <div className="stat-pill">
              <span className="stat-value">{stats.total}</span>
              <span className="stat-label">Total</span>
            </div>
            <div className="stat-pill stat-pill-success">
              <span className="stat-value">{stats.scheduled}</span>
              <span className="stat-label">Scheduled</span>
            </div>
            <div className="stat-pill stat-pill-warning">
              <span className="stat-value">{stats.paused}</span>
              <span className="stat-label">Paused</span>
            </div>
            {stats.failed > 0 && (
              <div className="stat-pill stat-pill-error">
                <span className="stat-value">{stats.failed}</span>
                <span className="stat-label">Failed</span>
              </div>
            )}
            {stats.unhealthy > 0 && (
              <div className="stat-pill stat-pill-critical">
                <span className="stat-value">{stats.unhealthy}</span>
                <span className="stat-label">Unhealthy</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {stats.unhealthy > 0 && (
        <div className="alert alert-error">
          <span className="alert-icon">⚠</span>
          <span className="alert-message">
            {stats.unhealthy} job{stats.unhealthy > 1 ? 's' : ''} require attention. Check failure details and retry.
          </span>
        </div>
      )}

      <div className="sessions-table-container cron-table-container">
        {cronQuery.isLoading ? (
          <div className="state-container state-loading">
            <div className="spinner" />
            <p>Loading jobs...</p>
          </div>
        ) : null}

        {cronQuery.isError ? (
          <div className="state-container state-error">
            <h3>Failed to load cron jobs</h3>
            <p>Unable to connect to API</p>
            <button className="btn btn-primary" onClick={() => cronQuery.refetch()}>
              Retry
            </button>
          </div>
        ) : null}

        {!cronQuery.isLoading && !cronQuery.isError && rows.length === 0 && (
          <div className="state-container state-empty">
            <h3>No jobs found</h3>
            <p>No cron jobs match the current instance filter.</p>
          </div>
        )}

        {!cronQuery.isLoading && !cronQuery.isError && rows.length > 0 && (
          <table className="data-table cron-table">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      onClick={header.column.getToggleSortingHandler()}
                      className={header.column.getIsSorted() ? 'sorted' : ''}
                    >
                      {header.isPlaceholder
                        ? null
                        : flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === 'asc' ? ' ▲' : null}
                      {header.column.getIsSorted() === 'desc' ? ' ▼' : null}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr
                  key={row.id}
                  className={`job-row job-row-${row.original.status} ${row.original.failure_count >= 3 ? 'job-row-unhealthy' : ''}`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <EditJobModal
        key={editingJob?.id ?? 'closed'}
        job={editingJob}
        isOpen={!!editingJob}
        onClose={() => setEditingJob(null)}
        onSave={(id, data) => updateMutation.mutate({ id, data })}
        isPending={updateMutation.isPending}
      />

      <ErrorDetailModal
        job={errorJob}
        isOpen={!!errorJob}
        onClose={() => setErrorJob(null)}
      />
    </div>
  )
}
