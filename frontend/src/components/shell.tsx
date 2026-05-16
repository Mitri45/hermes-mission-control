import { Link, Outlet, useMatchRoute } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAppState } from '../lib/state'
import type { InstanceFilter } from '../types'
import hermesLogo from '../assets/hermes-logo-320.webp'

interface NavItemProps {
  to: string
  label: string
  badge?: number
}

function NavItem({ to, label, badge }: NavItemProps) {
  const matchRoute = useMatchRoute()
  const isActive = Boolean(matchRoute({ to }))

  return (
    <li className={`nav-item ${isActive ? 'active' : ''}`}>
      <Link to={to} className="nav-link">
        <span>{label}</span>
        {typeof badge === 'number' ? <span className="nav-badge">{badge}</span> : null}
      </Link>
    </li>
  )
}

function InstanceTabs() {
  const { instance, setInstance } = useAppState()
  const tabs: InstanceFilter[] = ['all', 'pc', 'pi']

  return (
    <div className="instance-switcher">
      <span className="instance-label">Instance:</span>
      <div className="instance-tabs" role="tablist" aria-label="Instance filter">
        {tabs.map((value) => (
          <button
            key={value}
            className={`instance-tab ${instance === value ? 'active' : ''}`}
            data-instance={value}
            onClick={() => setInstance(value)}
          >
            {value.toUpperCase()}
          </button>
        ))}
      </div>
    </div>
  )
}

function StatusStrip() {
  const { instance } = useAppState()
  const statusQuery = useQuery({
    queryKey: ['status-strip-status'],
    queryFn: () => api.getSystemStatus('pc'),
    refetchInterval: 30000,
  })
  const harnessQuery = useQuery({
    queryKey: ['status-strip-harness'],
    queryFn: api.getHarnessStatus,
    refetchInterval: 30000,
  })

  const isOnline = !statusQuery.error && statusQuery.data
  const webhookOk = harnessQuery.data?.webhook?.status === 'healthy'

  return (
    <div className="status-strip">
      <div className="status-item" id="pc-status">
        <span className="status-indicator" data-state={isOnline ? 'online' : 'offline'} />
        <span className="status-label">PC</span>
        <span className="status-value">{isOnline ? 'Online' : 'Offline'}</span>
        <span className="status-uptime">{statusQuery.isFetching ? 'Syncing' : 'Ready'}</span>
      </div>
      <div className="status-divider" />
      <div className="status-item" id="pi-status">
        <span className="status-indicator" data-state={webhookOk ? 'online' : 'warning'} />
        <span className="status-label">PI</span>
        <span className="status-value">{webhookOk ? 'Connected' : 'Degraded'}</span>
        <span className="status-uptime">{harnessQuery.isFetching ? 'Syncing' : 'Watching'}</span>
      </div>
      <div className="status-divider" />
      <div className="status-mode">
        <span className="mode-label">Mode:</span>
        <span className="mode-value" id="system-mode">
          {instance === 'all' ? 'Unified' : instance.toUpperCase()}
        </span>
      </div>
    </div>
  )
}

export function ShellLayout() {
  const { instance } = useAppState()
  const cronQuery = useQuery({
    queryKey: ['nav-cron-badge', instance],
    queryFn: () => api.getCron(instance),
    refetchInterval: 30000,
  })
  const providerQuery = useQuery({
    queryKey: ['nav-provider-badge', instance],
    queryFn: () => api.getProviderStatus(instance),
    refetchInterval: 30000,
  })

  return (
    <div id="app" className="app">
      <header className="header">
        <div className="header-brand">
          <img className="logo" src={hermesLogo} alt="Hermes logo" />
          <h1 className="brand-title">Hermes</h1>
          <span className="brand-subtitle">Mission Control</span>
        </div>

        <InstanceTabs />

        <div className="header-actions">
          <button className="btn-icon" title="Refresh" onClick={() => window.location.reload()}>
            ↻
          </button>
          <button className="btn-icon" title="Settings">⚙</button>
        </div>
      </header>

      <StatusStrip />

      <div className="main-layout">
        <nav className="sidebar">
          <div className="nav-section">
            <span className="nav-section-title">Overview</span>
            <ul className="nav-list">
              <NavItem to="/" label="Dashboard" />
            </ul>
          </div>

          <div className="nav-section">
            <span className="nav-section-title">Management</span>
            <ul className="nav-list">
              <NavItem to="/cron" label="Cron Jobs" badge={cronQuery.data?.jobs?.length ?? 0} />
              <NavItem to="/digest" label="Daily Digest" />
            </ul>
          </div>

          <div className="nav-section">
            <span className="nav-section-title">System</span>
            <ul className="nav-list">
              <NavItem to="/providers" label="LLM Providers" badge={providerQuery.data?.summary?.active ?? 0} />
              <NavItem to="/sessions" label="Sessions" />
              <NavItem to="/operations" label="Operations Feed" />
              <NavItem to="/memory" label="Memory" />
            </ul>
          </div>
        </nav>

        <main className="content">
          <Outlet />
        </main>
      </div>

      <div id="toast-container" className="toast-container" />
    </div>
  )
}
