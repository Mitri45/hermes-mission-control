import { useEffect, useMemo, useRef, useState } from 'react'
import { buildOperationsStreamProtocols, buildOperationsStreamUrl } from '../lib/api'
import { shortDateTime } from '../lib/format'
import { useAppState } from '../lib/state'

/**
 * DIM-209 docs baseline reviewed on 2026-04-09:
 * - https://tanstack.com/start/latest/docs/framework/react/overview
 * - https://tanstack.com/router/latest/docs/framework/react/overview
 * - https://tanstack.com/query/latest/docs/framework/react/overview
 * - https://tanstack.com/table/latest/docs/guide/introduction
 * - https://tanstack.com/form/latest/docs/framework/react/overview
 * - https://ai-sdk.dev/docs/ai-sdk-ui/chatbot
 */

const MAX_SCROLLBACK = 300
const RECONNECT_BACKOFF_MS = [1000, 2000, 5000, 10000]

type ConnectionState = 'connecting' | 'open' | 'closed' | 'error'
type EventInstance = 'pc' | 'pi' | 'both'
type EventCategory = 'error' | 'tool_call' | 'thought' | 'completion' | 'other'
type FilterCategory = 'all' | 'error' | 'tool_call' | 'thought' | 'completion'

interface FeedEvent {
  id: string
  seq: number
  timestamp: string
  eventType: string
  category: EventCategory
  instance: EventInstance
  title: string
  details: string
  sessionId: string | null
  status: string | null
}

const FILTER_OPTIONS: Array<{ key: FilterCategory; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'error', label: 'Errors' },
  { key: 'tool_call', label: 'Tool Calls' },
  { key: 'thought', label: 'Thoughts' },
  { key: 'completion', label: 'Completions' },
]

function asText(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed.length ? trimmed : null
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (value && typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return null
    }
  }
  return null
}

function truncate(value: string, max: number = 220): string {
  if (value.length <= max) return value
  return `${value.slice(0, max - 1)}…`
}

function normalizeInstance(value: unknown): EventInstance {
  const raw = asText(value)?.toLowerCase()
  if (raw === 'pc') return 'pc'
  if (raw === 'pi') return 'pi'
  return 'both'
}

function categoryFromType(type: string): EventCategory {
  const normalized = type.toLowerCase()
  if (normalized === 'error' || normalized.endsWith('_error')) return 'error'
  if (normalized === 'tool_call' || normalized.startsWith('tool_') || normalized === 'file_op') {
    return 'tool_call'
  }
  if (normalized === 'thought') return 'thought'
  if (normalized === 'completion' || normalized === 'completed') return 'completion'
  return 'other'
}

function titleForEvent(type: string, category: EventCategory, payload: Record<string, unknown>): string {
  if (category === 'tool_call') {
    const tool = asText(payload.tool)
    if (tool) return `Tool call: ${tool}`
    const action = asText(payload.action)
    if (action) return `Tool action: ${action}`
    return 'Tool call'
  }
  if (category === 'error') return 'Error event'
  if (category === 'thought') return 'Thought event'
  if (category === 'completion') return 'Completion event'
  return `Event: ${type}`
}

function detailsForEvent(payload: Record<string, unknown>): string {
  const content = asText(payload.content)
  if (content) return truncate(content)

  const parts = [
    asText(payload.args),
    asText(payload.action),
    asText(payload.path),
    asText(payload.data),
  ].filter((item): item is string => Boolean(item))

  if (parts.length) {
    return truncate(parts.join(' • '))
  }
  return 'No event payload'
}

function normalizeIncomingEvent(raw: unknown, seq: number): FeedEvent | null {
  if (!raw || typeof raw !== 'object') return null
  const payload = raw as Record<string, unknown>
  const eventType = asText(payload.type) ?? 'unknown'
  const timestamp = asText(payload.timestamp) ?? new Date().toISOString()
  const category = categoryFromType(eventType)
  const instance = normalizeInstance(
    payload.instance
    ?? payload.source_instance
    ?? payload.sourceInstance
    ?? payload.target_instance,
  )
  const sessionId = asText(payload.session_id ?? payload.sessionId)
  const status = asText(payload.status)

  return {
    id: `ops-${seq}`,
    seq,
    timestamp,
    eventType,
    category,
    instance,
    title: titleForEvent(eventType, category, payload),
    details: detailsForEvent(payload),
    sessionId,
    status,
  }
}

function connectionLabel(state: ConnectionState): string {
  if (state === 'open') return 'Live'
  if (state === 'connecting') return 'Connecting'
  if (state === 'closed') return 'Disconnected'
  return 'Error'
}

export function OperationsRoute() {
  const { instance } = useAppState()
  const [events, setEvents] = useState<FeedEvent[]>([])
  const [selectedFilter, setSelectedFilter] = useState<FilterCategory>('all')
  const [isPaused, setIsPaused] = useState(false)
  const [bufferedCount, setBufferedCount] = useState(0)
  const [connectionState, setConnectionState] = useState<ConnectionState>('connecting')
  const [connectionMessage, setConnectionMessage] = useState<string>('')
  const [reconnectNonce, setReconnectNonce] = useState(0)

  const seqRef = useRef(0)
  const pausedRef = useRef(isPaused)
  const pausedBufferRef = useRef<FeedEvent[]>([])

  useEffect(() => {
    pausedRef.current = isPaused
  }, [isPaused])

  useEffect(() => {
    if (isPaused) return
    if (pausedBufferRef.current.length === 0) return

    const pending = pausedBufferRef.current
    pausedBufferRef.current = []
    setBufferedCount(0)
    setEvents((prev) => [...prev, ...pending].slice(-MAX_SCROLLBACK))
  }, [isPaused])

  useEffect(() => {
    let stopped = false
    let socket: WebSocket | null = null
    let reconnectTimer: number | null = null
    let reconnectAttempt = 0

    const scheduleReconnect = (reason: string) => {
      if (stopped) return
      const delay = RECONNECT_BACKOFF_MS[Math.min(reconnectAttempt, RECONNECT_BACKOFF_MS.length - 1)]
      reconnectAttempt += 1
      setConnectionState('closed')
      setConnectionMessage(`${reason} Reconnecting in ${Math.round(delay / 1000)}s.`)
      reconnectTimer = window.setTimeout(connectStream, delay)
    }

    const connectStream = () => {
      if (stopped) return
      const url = buildOperationsStreamUrl()
      if (!url) {
        setConnectionState('error')
        setConnectionMessage('Unable to build stream URL.')
        return
      }

      setConnectionState('connecting')
      setConnectionMessage('')
      const protocols = buildOperationsStreamProtocols()
      socket = protocols.length > 0 ? new WebSocket(url, protocols) : new WebSocket(url)

      socket.onopen = () => {
        reconnectAttempt = 0
        setConnectionState('open')
        setConnectionMessage('')
      }

      socket.onmessage = (messageEvent) => {
        try {
          const raw = JSON.parse(messageEvent.data) as unknown
          const normalized = normalizeIncomingEvent(raw, seqRef.current)
          seqRef.current += 1
          if (!normalized) return

          if (pausedRef.current) {
            pausedBufferRef.current = [...pausedBufferRef.current, normalized].slice(-MAX_SCROLLBACK)
            setBufferedCount(pausedBufferRef.current.length)
            return
          }
          setEvents((prev) => [...prev, normalized].slice(-MAX_SCROLLBACK))
        } catch (error) {
          // Ignore malformed messages so the feed remains non-blocking.
          if (import.meta.env.DEV) {
            console.warn('Failed to parse operations event', messageEvent.data, error)
          }
        }
      }

      socket.onerror = () => {
        setConnectionState('error')
        setConnectionMessage('WebSocket transport error.')
      }

      socket.onclose = (closeEvent) => {
        socket = null
        if (stopped) return
        if (closeEvent.code === 1008) {
          setConnectionState('error')
          setConnectionMessage('Unauthorized stream. Refresh credentials and click Reconnect.')
          return
        }
        scheduleReconnect(`Stream closed (code ${closeEvent.code}).`)
      }
    }

    connectStream()

    return () => {
      stopped = true
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer)
      }
      if (socket) {
        socket.close(1000, 'Operations route closed')
      }
    }
  }, [reconnectNonce])

  const instanceScopedEvents = useMemo(() => {
    return events.filter((event) => {
      if (instance === 'all') return true
      if (event.instance === 'both') return true
      return event.instance === instance
    })
  }, [events, instance])

  const filterCounts = useMemo(() => {
    return {
      all: instanceScopedEvents.length,
      error: instanceScopedEvents.filter((event) => event.category === 'error').length,
      tool_call: instanceScopedEvents.filter((event) => event.category === 'tool_call').length,
      thought: instanceScopedEvents.filter((event) => event.category === 'thought').length,
      completion: instanceScopedEvents.filter((event) => event.category === 'completion').length,
    }
  }, [instanceScopedEvents])

  const visibleEvents = useMemo(() => {
    if (selectedFilter === 'all') return instanceScopedEvents
    return instanceScopedEvents.filter((event) => event.category === selectedFilter)
  }, [instanceScopedEvents, selectedFilter])

  const clearFeed = () => {
    pausedBufferRef.current = []
    setBufferedCount(0)
    setEvents([])
  }

  return (
    <div id="operations-view" className="view">
      <div className="page-header">
        <h2 className="page-title">Operations Feed</h2>
        <p className="page-subtitle">Live runtime stream with filtering, pause/resume, and bounded scrollback</p>
      </div>

      <section className="section">
        <div className="operations-toolbar">
          <div className="operations-connection">
            <span className={`operations-dot state-${connectionState}`} />
            <span className="operations-connection-label">Stream: {connectionLabel(connectionState)}</span>
            {connectionMessage ? (
              <span className="operations-connection-message">{connectionMessage}</span>
            ) : null}
          </div>
          <div className="operations-actions">
            <button className="btn" type="button" onClick={() => setIsPaused((value) => !value)}>
              {isPaused ? 'Resume Stream' : 'Pause Stream'}
            </button>
            <button className="btn" type="button" onClick={() => setReconnectNonce((value) => value + 1)}>
              Reconnect
            </button>
            <button className="btn" type="button" onClick={clearFeed}>
              Clear Feed
            </button>
          </div>
        </div>

        <div className="operations-meta">
          <span>Instance: {instance.toUpperCase()}</span>
          <span>Scrollback: {events.length}/{MAX_SCROLLBACK}</span>
          {bufferedCount > 0 ? <span>Buffered while paused: {bufferedCount}</span> : null}
        </div>

        <div className="operations-filters" role="tablist" aria-label="Operation event filters">
          {FILTER_OPTIONS.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`filter-btn ${selectedFilter === option.key ? 'active' : ''}`}
              onClick={() => setSelectedFilter(option.key)}
            >
              {option.label}
              <span className="filter-count">{filterCounts[option.key]}</span>
            </button>
          ))}
        </div>

        <div className="operations-feed" role="log" aria-live="polite" aria-relevant="additions">
          {visibleEvents.length === 0 ? (
            <p className="empty-text">No events for this filter yet.</p>
          ) : (
            visibleEvents.map((event) => (
              <article key={event.id} className={`operations-event event-${event.category}`}>
                <div className="operations-event-head">
                  <span className={`operations-event-type event-type-${event.category}`}>
                    {event.category === 'other' ? event.eventType : event.category.replace('_', ' ')}
                  </span>
                  <span className={`instance-badge instance-${event.instance}`}>{event.instance.toUpperCase()}</span>
                  <span className="operations-event-time">{shortDateTime(event.timestamp)}</span>
                </div>
                <div className="operations-event-title">{event.title}</div>
                <p className="operations-event-details">{event.details}</p>
                <div className="operations-event-meta-row">
                  <span>#{event.seq}</span>
                  <span>{event.sessionId ? `Session ${event.sessionId}` : 'Session --'}</span>
                  <span>{event.status ? `Status ${event.status}` : 'Status --'}</span>
                </div>
              </article>
            ))
          )}
        </div>
      </section>
    </div>
  )
}
