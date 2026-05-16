import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { PropsWithChildren } from 'react'
import type { InstanceFilter } from '../types'

interface AppState {
  instance: InstanceFilter
  setInstance: (value: InstanceFilter) => void
}

const AppStateContext = createContext<AppState | null>(null)
const INSTANCE_STORAGE_KEY = 'hermes.dashboardInstance'

function readPersistedInstance(): InstanceFilter {
  if (typeof window === 'undefined') return 'all'
  const stored = window.localStorage.getItem(INSTANCE_STORAGE_KEY)
  if (stored === 'pc' || stored === 'pi' || stored === 'all') return stored
  return 'all'
}

export function AppStateProvider({ children }: PropsWithChildren) {
  const [instance, setInstance] = useState<InstanceFilter>(readPersistedInstance)

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem(INSTANCE_STORAGE_KEY, instance)
  }, [instance])

  const value = useMemo(() => ({ instance, setInstance }), [instance])
  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>
}

export function useAppState(): AppState {
  const context = useContext(AppStateContext)
  if (!context) throw new Error('useAppState must be used inside AppStateProvider')
  return context
}
