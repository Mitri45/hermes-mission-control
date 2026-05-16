import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { AppStateProvider } from './lib/state'
import { clearDashboardBearerToken, setDashboardBearerToken } from './lib/api'
import { makeRouter } from './router'
import './styles.css'

function bootstrapDashboardTokenFromHash(): void {
  if (typeof window === 'undefined') return
  const hash = window.location.hash.replace(/^#/, '')
  if (!hash) return
  const params = new URLSearchParams(hash)
  const clearToken = params.get('clearToken')
  if (clearToken === '1' || clearToken?.toLowerCase() === 'true') {
    clearDashboardBearerToken()
  }
  const token = params.get('token')
  if (token) {
    setDashboardBearerToken(token)
  }
  if (clearToken || token) {
    const cleanUrl = `${window.location.pathname}${window.location.search}`
    window.history.replaceState(null, '', cleanUrl)
  }
}

bootstrapDashboardTokenFromHash()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

const router = makeRouter(queryClient)

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Dashboard root container not found')
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppStateProvider>
        <RouterProvider router={router} />
      </AppStateProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
