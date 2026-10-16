import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { App } from './App'
import { queryClient } from './lib/queryClient'

// These tests exercise the GATE → reveal → launch-banner flow, not the app's pages (which have
// their own tests). Stub the default route so revealing MainApp doesn't drag in BrowsePage's data
// fetching, and stub the WS-backed hooks (jsdom has no WebSocket).
vi.mock('@/pages/BrowsePage', () => ({ BrowsePage: () => <div>Browse</div> }))
vi.mock('@/pages/IndexerPage', () => ({ IndexerPage: () => <div>Indexer destination</div> }))
vi.mock('@/pages/SettingsPage', () => ({ SettingsPage: () => <div>Settings destination</div> }))
vi.mock('./hooks/useIndexerStatus', () => ({
  useIndexerStatus: vi.fn(() => ({ status: null, connected: false })),
  useIndexerRunning: vi.fn(() => false),
}))
vi.mock('./hooks/useSetupWS', () => ({
  useSetupWS: vi.fn(() => ({ models: null, complete: false })),
}))

// URL-aware fetch: /health drives the gate → ready; /api/setup/job decides first-run vs warm
// launch (no job and ready → straight to the app). Any other API call the mounted app makes returns
// a benign empty payload so MainApp renders without throwing.
function routedFetch(setup: () => unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/setup/job')) {
      return Promise.resolve({ ok: true, json: async () => setup() } as Response)
    }
    if (url.includes('/health')) {
      return Promise.resolve({ ok: true, json: async () => ({ status: 'ready' }) } as Response)
    }
    return Promise.resolve({ ok: true, json: async () => ({}) } as Response)
  })
}

// The gate→reveal chain is a fixed multi-hop async chain (/health → /api/setup/job → reveal);
// fake timers let us own the single clock and drain each hop deterministically rather than betting
// the tail settles inside a wall-clock budget on a loaded runner (the historical ~1/168 flake).
async function settleLaunchChain() {
  for (let i = 0; i < 8; i++) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100)
    })
  }
}

// jsdom has no IntersectionObserver; BrowsePage (the default /browse route the revealed app mounts)
// uses it for infinite scroll — stub it the same way the page tests do.
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return []
  }
}

describe('App launch flow', () => {
  beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', MockIntersectionObserver)
    vi.useFakeTimers()
    queryClient.clear()
    window.history.replaceState({}, '', '/browse')
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    queryClient.clear()
  })

  it('reveals the app and shows the launch banner once the backend and models are ready', async () => {
    window.history.replaceState({}, '', '/browse?launch=1')
    // Warm launch: /health and setup-job report ready, so the gate reveals AppInner.
    vi.stubGlobal('fetch', routedFetch(() => ({ ready: true, job: null, read_only_mode: false })))

    render(<App />)
    await settleLaunchChain()

    expect(screen.getByLabelText(/media search agent launch splash/i)).toBeInTheDocument()
    // App strips ?launch on mount via history.replaceState.
    expect(window.location.search).toBe('')
    expect(screen.queryByRole('link', { name: 'Keyframes' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Adapter Workbench' })).not.toBeInTheDocument()
  })

  it.each([
    ['/keyframes', '/indexer', 'Indexer destination'],
    ['/adapters', '/settings', 'Settings destination'],
  ])('redirects removed page %s to %s', async (from, to, destination) => {
    window.history.replaceState({}, '', from)
    vi.stubGlobal('fetch', routedFetch(() => ({ ready: true, job: null, read_only_mode: false })))

    render(<App />)
    await settleLaunchChain()

    expect(screen.getByText(destination)).toBeInTheDocument()
    expect(window.location.pathname).toBe(to)
  })

  it('dismisses the launch banner', async () => {
    window.history.replaceState({}, '', '/browse?launch=1')
    vi.stubGlobal('fetch', routedFetch(() => ({ ready: true, job: null, read_only_mode: false })))

    render(<App />)
    await settleLaunchChain()

    expect(screen.getByLabelText(/media search agent launch splash/i)).toBeInTheDocument()
    // fireEvent (not userEvent) so the click dispatches synchronously and never stalls on the
    // frozen fake clock; the onClick state update (splash → hidden) is act-flushed.
    fireEvent.click(screen.getByRole('button', { name: /dismiss launch banner/i }))
    expect(screen.queryByLabelText(/media search agent launch splash/i)).not.toBeInTheDocument()
  })

  it('stays on the splash (app gated) while first-run model downloads are still needed', async () => {
    // First run: /health ready but no setup job exists → confirmation is shown and app remains gated.
    vi.stubGlobal(
      'fetch',
      routedFetch(() => ({
        ready: false,
        job: null,
        read_only_mode: false,
      })),
    )

    render(<App />)
    await settleLaunchChain()

    expect(screen.getByText('Finish setting up')).toBeInTheDocument()
    // The app shell (main navigation) must not have mounted behind the gate.
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})
