import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { shortDateTime } from '../lib/format'
import type { ChatMessage } from '../types'

const CHAT_SESSION_STORAGE_KEY = 'hermes.missionControl.chatSessionId'

function generateSessionId(): string {
  return `mc_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

function readStoredSessionId(): string {
  if (typeof window === 'undefined') return 'mc_default'
  const existing = window.localStorage.getItem(CHAT_SESSION_STORAGE_KEY)?.trim()
  if (existing) return existing
  const fresh = generateSessionId()
  window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, fresh)
  return fresh
}

function writeStoredSessionId(sessionId: string): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(CHAT_SESSION_STORAGE_KEY, sessionId)
}

function formatHost(url: string | null | undefined): string {
  if (!url) return 'Not configured'
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function messageLabel(message: ChatMessage): string {
  if (message.tool_name) return `${message.role} · ${message.tool_name}`
  return message.role
}

export function ChatFoundation() {
  const queryClient = useQueryClient()
  const [input, setInput] = useState('')
  const [sessionId, setSessionId] = useState(() => readStoredSessionId())

  useEffect(() => {
    writeStoredSessionId(sessionId)
  }, [sessionId])

  const configQuery = useQuery({
    queryKey: ['chat-config'],
    queryFn: api.getConfig,
    refetchInterval: 30000,
  })

  const harnessQuery = useQuery({
    queryKey: ['chat-harness-status'],
    queryFn: api.getHarnessStatus,
    refetchInterval: 30000,
  })

  const transcriptQuery = useQuery({
    queryKey: ['mission-control-chat', sessionId],
    queryFn: () => api.getChatSession(sessionId),
    refetchInterval: 15000,
  })

  const chatMutation = useMutation({
    mutationFn: (message: string) => api.sendChat(message, sessionId, false),
    onSuccess: (response) => {
      if (response.session_id && response.session_id !== sessionId) {
        setSessionId(response.session_id)
      }
      queryClient.invalidateQueries({ queryKey: ['mission-control-chat', response.session_id || sessionId] })
      setInput('')
    },
  })

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const cleaned = input.trim()
    if (!cleaned || chatMutation.isPending) return
    chatMutation.mutate(cleaned)
  }

  const handleReset = () => {
    const nextSessionId = generateSessionId()
    setSessionId(nextSessionId)
    setInput('')
  }

  const transcript = transcriptQuery.data
  const messages = transcript?.messages ?? []
  const config = configQuery.data
  const webhookStatus = harnessQuery.data?.webhook?.status ?? 'unknown'

  const effectiveModel = transcript?.model ?? config?.model ?? 'Loading…'
  const effectiveProvider = transcript?.provider ?? config?.provider ?? 'Loading…'
  const effectiveBaseUrl = transcript?.base_url ?? config?.base_url

  const transcriptStats = useMemo(() => {
    const users = messages.filter((message) => message.role === 'user').length
    const assistants = messages.filter((message) => message.role === 'assistant').length
    const tools = messages.filter((message) => message.role === 'tool').length
    return { users, assistants, tools }
  }, [messages])

  return (
    <section className="section" aria-label="chat-foundation">
      <div className="chat-section-header">
        <h3 className="section-title">Mission Control Chat</h3>
        <button className="btn btn-secondary" type="button" onClick={handleReset}>
          New session
        </button>
      </div>
      <div className="chat-foundation">
        <div className="chat-metadata-grid">
          <div className="chat-meta-card">
            <span className="chat-meta-label">Configured model</span>
            <strong>{effectiveModel}</strong>
          </div>
          <div className="chat-meta-card">
            <span className="chat-meta-label">Provider</span>
            <strong>{effectiveProvider}</strong>
          </div>
          <div className="chat-meta-card">
            <span className="chat-meta-label">Base URL</span>
            <strong>{formatHost(effectiveBaseUrl)}</strong>
          </div>
          <div className="chat-meta-card">
            <span className="chat-meta-label">Session ID</span>
            <strong>{sessionId}</strong>
          </div>
          <div className="chat-meta-card">
            <span className="chat-meta-label">Webhook status</span>
            <strong>{webhookStatus}</strong>
          </div>
          <div className="chat-meta-card">
            <span className="chat-meta-label">Transcript</span>
            <strong>
              {transcriptStats.users} user · {transcriptStats.assistants} assistant · {transcriptStats.tools} tool
            </strong>
          </div>
        </div>

        <div className="chat-foundation-note">
          <p>
            This panel now runs a real Hermes Mission Control session through <code>/api/chat</code>. The transcript is restored from
            the shared session store, so reloads continue the same conversation until you start a new session.
          </p>
        </div>

        <div className="chat-transcript">
          {messages.length === 0 ? (
            <p className="empty-text">No chat messages yet</p>
          ) : (
            messages.map((message, index) => (
              <div key={`${message.role}-${message.timestamp ?? index}-${index}`} className={`chat-message chat-message-${message.role}`}>
                <div className="chat-message-header">
                  <span className="chat-message-role">{messageLabel(message)}</span>
                  <span className="chat-message-time">{shortDateTime(message.timestamp)}</span>
                </div>
                <div className="chat-message-content">{message.content || '(empty)'}</div>
              </div>
            ))
          )}
        </div>

        <form onSubmit={handleSubmit} className="inline-form">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Send a Mission Control message"
            className="text-input"
          />
          <button className="btn btn-primary" type="submit" disabled={chatMutation.isPending || !input.trim()}>
            {chatMutation.isPending ? 'Sending…' : 'Send'}
          </button>
        </form>

        {chatMutation.isError ? (
          <p className="form-error">{(chatMutation.error as Error).message || 'Chat request failed'}</p>
        ) : null}

        <p className="inline-note">
          Stored messages: {transcript?.message_count ?? 0} · backend session persists in Hermes state.db
        </p>
      </div>
    </section>
  )
}
