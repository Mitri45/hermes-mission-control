import { useQuery } from '@tanstack/react-query'
import { ChatFoundation } from '../components/chatFoundation'
import { api } from '../lib/api'
import { shortDateTime } from '../lib/format'
import type { AgentSession } from '../types'

function titleForSession(session: AgentSession): string {
  const title = session.issue_title?.trim()
  if (title) return title
  const issueId = session.issue_id?.trim()
  if (issueId) return issueId
  return session.id
}

function statusLabel(session: AgentSession): string {
  return session.status === 'running' ? 'live' : session.status
}

function pathLabel(path: string | null | undefined): string | null {
  if (!path) return null
  const segments = path.split('/').filter(Boolean)
  const tail = segments.slice(-2).join('/')
  return tail || path
}

function secondaryMeta(session: AgentSession): string {
  const parts = [
    session.platform?.toUpperCase(),
    session.backend,
    session.message_count ? `${session.message_count} msgs` : null,
    pathLabel(session.worktree),
  ].filter(Boolean)
  return parts.join(' • ')
}

function SessionCard({ session, live }: { session: AgentSession; live: boolean }) {
  const detail = session.summary?.trim() || session.prompt?.trim() || 'No session summary captured'
  const when = session.last_updated_at ?? session.started_at

  return (
    <div className="session-card" key={session.id}>
      <div className="session-card-header">
        <div className="session-card-title-group">
          <div className="activity-title">{titleForSession(session)}</div>
          <div className="session-meta-row">
            <span className={`session-pill ${live ? 'session-pill-live' : ''}`}>{statusLabel(session)}</span>
            {session.source ? <span className="session-pill">{session.source}</span> : null}
            {session.issue_id ? <span className="session-pill">{session.issue_id}</span> : null}
          </div>
        </div>
        <div className="activity-time">{shortDateTime(when)}</div>
      </div>
      <div className="activity-desc">{secondaryMeta(session)}</div>
      {session.base_url ? <div className="session-submeta">{session.base_url}</div> : null}
      <div className="session-summary">{detail}</div>
    </div>
  )
}

export function SessionsRoute() {
  const sessionsQuery = useQuery({
    queryKey: ['sessions-route'],
    queryFn: api.getSessions,
    refetchInterval: 30000,
  })

  const sessions = sessionsQuery.data?.sessions ?? []
  const activeSessions = sessions.filter((session) => session.status === 'running')
  const recentSessions = sessions.filter((session) => session.status !== 'running')

  return (
    <div id="sessions-view" className="view">
      <div className="page-header">
        <h2 className="page-title">Sessions</h2>
        <p className="page-subtitle">Live workers, recent Hermes session archives, and a local chat transport test</p>
      </div>
      <section className="section">
        <h3 className="section-title">Live Sessions</h3>
        <div className="sessions-table-container" id="sessions-table-active">
          {activeSessions.length === 0 ? <p className="empty-text">No active sessions</p> : null}
          {activeSessions.map((session) => (
            <SessionCard key={session.id} session={session} live />
          ))}
        </div>
      </section>

      <section className="section">
        <h3 className="section-title">Recent Sessions</h3>
        <div className="sessions-table-container" id="sessions-table-recent">
          {recentSessions.length === 0 ? <p className="empty-text">No recent sessions</p> : null}
          {recentSessions.map((session) => (
            <SessionCard key={session.id} session={session} live={false} />
          ))}
        </div>
      </section>

      <ChatFoundation />
    </div>
  )
}
