const ISO_TIMEZONE_SUFFIX = /(Z|[+-]\d{2}:\d{2})$/i

export function normalizeTimestamp(value?: string): string {
  if (!value) return ''
  return ISO_TIMEZONE_SUFFIX.test(value) ? value : `${value}Z`
}

export function parseTimestampMs(value?: string): number {
  const normalized = normalizeTimestamp(value)
  if (!normalized) return Number.NaN
  const parsed = Date.parse(normalized)
  return Number.isFinite(parsed) ? parsed : Number.NaN
}

export function percent(value: number): string {
  return `${Math.max(0, Math.min(100, Math.round(value)))}%`
}

export function ratioPercent(used: number, total: number): number {
  if (!total) return 0
  return (used / total) * 100
}

export function shortDateTime(value?: string): string {
  if (!value) return '--'
  const date = new Date(normalizeTimestamp(value))
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function timeAgo(value?: string): string {
  if (!value) return '--'
  const timestampMs = parseTimestampMs(value)
  if (!Number.isFinite(timestampMs)) return '--'
  const seconds = Math.max(0, Math.floor((Date.now() - timestampMs) / 1000))
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

export function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return '--'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

export function formatDateHeader(dateStr: string): string {
  const date = new Date(normalizeTimestamp(dateStr))
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  const isSameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()

  if (isSameDay(date, today)) return 'Today'
  if (isSameDay(date, yesterday)) return 'Yesterday'

  return date.toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

export function formatRelativeTime(dateStr: string): string {
  return timeAgo(dateStr)
}

export function formatReplicationLag(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return '--'
  if (seconds < 1) return '< 1s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

export function formatBytes(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = value
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  const precision = size >= 100 ? 0 : size >= 10 ? 1 : 2
  return `${size.toFixed(precision)} ${units[unitIndex]}`
}
