import './style.css'

import { missionControlApi } from './api'
import type { MissionControlSection } from './types'

function MissionControlRoot() {
  const sdk = window.__HERMES_PLUGIN_SDK__
  if (!sdk) {
    return null
  }
  const React = sdk.React
  const { useEffect, useState } = sdk.hooks
  const { Card, CardHeader, CardTitle, CardContent, Badge, Button } = sdk.components

  const stateSummary = useState(null)
  const summary = stateSummary[0]
  const setSummary = stateSummary[1]
  const stateError = useState('')
  const error = stateError[0]
  const setError = stateError[1]
  const stateLoading = useState(true)
  const loading = stateLoading[0]
  const setLoading = stateLoading[1]

  const load = () => {
    setLoading(true)
    setError('')
    missionControlApi.summary()
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const sections: MissionControlSection[] = summary?.sections ?? [
    { id: 'fleet-health', label: 'Fleet Health', status: 'planned' },
    { id: 'hindsight', label: 'Hindsight Bank', status: 'planned' },
    { id: 'memory-ingest', label: 'Memory Ingest', status: 'planned' },
    { id: 'linear-harness', label: 'Linear Harness', status: 'planned' },
    { id: 'digest', label: 'Digest', status: 'planned' },
    { id: 'provider-status', label: 'Provider Status', status: 'planned' },
    { id: 'operations', label: 'Operations Stream', status: 'planned' },
  ]

  return React.createElement('div', { className: 'mission-control-plugin' },
    React.createElement('div', { className: 'mission-control-header' },
      React.createElement('div', null,
        React.createElement('p', { className: 'mission-control-kicker' }, 'Ops cockpit'),
        React.createElement('h1', null, 'Mission Control'),
        React.createElement('p', { className: 'mission-control-subtitle' },
          'Custom ops panels are being migrated from the standalone Mission Control service into upstream Hermes dashboard plugins.'
        ),
      ),
      React.createElement(Button, { onClick: load, disabled: loading }, loading ? 'Checking…' : 'Refresh'),
    ),
    error ? React.createElement('div', { className: 'mission-control-error' }, error) : null,
    React.createElement('div', { className: 'mission-control-grid' },
      sections.map((section: MissionControlSection) => React.createElement(Card, { key: section.id, className: 'mission-control-card' },
        React.createElement(CardHeader, null,
          React.createElement(CardTitle, null, section.label),
        ),
        React.createElement(CardContent, null,
          React.createElement(Badge, { variant: section.status === 'ready' ? 'default' : 'secondary' }, section.status),
          React.createElement('p', null, section.id),
        ),
      )),
    ),
  )
}

window.__HERMES_PLUGINS__?.register('mission-control', MissionControlRoot)
