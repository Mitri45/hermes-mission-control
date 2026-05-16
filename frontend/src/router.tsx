import { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { ShellLayout } from './components/shell'
import { DashboardRoute } from './routes/dashboard'
import { CronRoute } from './routes/cron'
import { DigestRoute } from './routes/digest'
import { SessionsRoute } from './routes/sessions'
import { MemoryRoute } from './routes/memory'
import { ProvidersRoute } from './routes/providers'
import { OperationsRoute } from './routes/operations'

interface RouterContext {
  queryClient: QueryClient
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: ShellLayout,
})

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: DashboardRoute,
})

const cronRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/cron',
  component: CronRoute,
})

const digestRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/digest',
  component: DigestRoute,
})

const sessionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/sessions',
  component: SessionsRoute,
})

const operationsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/operations',
  component: OperationsRoute,
})

const memoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/memory',
  component: MemoryRoute,
})

const providersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/providers',
  component: ProvidersRoute,
})

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  cronRoute,
  digestRoute,
  sessionsRoute,
  operationsRoute,
  memoryRoute,
  providersRoute,
])

export function makeRouter(queryClient: QueryClient) {
  return createRouter({
    routeTree,
    context: { queryClient },
    basepath: '/dashboard',
    defaultPreload: 'intent',
  })
}
