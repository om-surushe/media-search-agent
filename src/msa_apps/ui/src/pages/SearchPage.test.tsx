import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { SearchPage } from './SearchPage'

// ── WebSocket mock ─────────────────────────────────────────────────────────

type WSMessage = { type: string; status: object; log: string[] }

class MockWebSocket {
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  static lastInstance: MockWebSocket | null = null
  static pendingMessage: WSMessage | null = null

  constructor(_url: string) {
    MockWebSocket.lastInstance = this
    if (MockWebSocket.pendingMessage) {
      const msg = MockWebSocket.pendingMessage
      setTimeout(() => this.onmessage?.({ data: JSON.stringify(msg) }), 0)
    }
  }
  close() {}
}

const idleUpdate: WSMessage = {
  type: 'update',
  status: { status: 'idle', run_id: null, started_at: null, finished_at: null, elapsed_seconds: null, return_code: null },
  log: [],
}

const runningUpdate: WSMessage = {
  type: 'update',
  status: { status: 'running', run_id: 'abc', started_at: null, finished_at: null, elapsed_seconds: 10, return_code: null, summary: { phase: 'processing' } },
  log: [],
}

// M-8/S-2: the Qdrant lock window — the only slice of a run where search is
// briefly unavailable (sentinel-file handoff).
const exportingUpdate: WSMessage = {
  type: 'update',
  status: { status: 'running', run_id: 'abc', started_at: null, finished_at: null, elapsed_seconds: 10, return_code: null, summary: { phase: 'exporting' } },
  log: [],
}

// ── Helpers ────────────────────────────────────────────────────────────────

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.stubGlobal('WebSocket', MockWebSocket)
  MockWebSocket.lastInstance = null
  MockWebSocket.pendingMessage = idleUpdate
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve([]) })
  ))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ── Tests ──────────────────────────────────────────────────────────────────

describe('SearchPage', () => {
  it('opens the shared drawer and displays stored AI caption provenance', async () => {
    const payload = {
      media: { id: 'captioned-image', type: 'image', mime: 'image/jpeg', filename: 'dog.jpg', source_name: 'fixture', source_folder: 'photos', path: '/tmp/dog.jpg', size_bytes: 12, width: 2, height: 2, duration: null, captured_at: null, added_at: null, filesystem_mtime: null, camera: null, lens: null, gps_lat: null, gps_lon: null, place: null, gps_processed: false, gps_data_mode: null, gps_sensitive: false, hash_blake3: null, fingerprints: [] },
      descriptions: { image_caption: { status: 'available', text: 'A black dog at a fence.', model_name: 'mlx/model' }, image_captions: [{ caption: 'A black dog at a fence.', model_id: 'mlx/model', prompt_version: 'caption-v1', generated_at_utc: '2026-10-14T10:00:00+00:00', status: 'completed' }], video_summary: { status: 'not_generated', text: null, model_name: null }, scenes: [] },
      pipeline_status: [],
      embeddings: { image: { present: false, count: 0, dimensions: null, model: null, created_at: null }, keyframes: { present: false, count: 0, dimensions: null, model: null, created_at: null } },
      faces: [], face_count: 0, objects: [], object_label_count: 0, objects_evidence: 'none', stored_tags: [], shots: [], total_shots: 0, keyframes: [], total_keyframes: 0,
      transcript: { status: 'unsupported', model_name: null, model_revision: null, runtime_version: null, language: null, processed_at: null, error_code: null, segments: [], total_segments: 0 },
    }
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      const body = url === '/search' ? {
        results: [{ id: 'captioned-image', path: '/tmp/dog.jpg', thumbnail: null, score: null, caption_excerpt: 'black dog', tags: [], type: null, timestamp: null, shot_id: null, date: null, gps_lat: null, gps_lon: null, place: null, why: 'Caption match' }],
        search_id: null,
      } : url.includes('/intelligence') ? payload : []
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
    }))
    const { container } = renderPage()
    fireEvent.change(screen.getByPlaceholderText(/describe what you're looking for/i), { target: { value: 'dog' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(await screen.findByText(/caption match:/i)).toBeInTheDocument()
    const mediaButton = container.querySelector('button img[src*="captioned-image"]')?.closest('button')
    expect(mediaButton).not.toBeNull()
    fireEvent.click(mediaButton!)

    expect(await screen.findByText('A black dog at a fence.')).toBeInTheDocument()
    expect(await screen.findByText('mlx/model')).toBeInTheDocument()
    expect(await screen.findByText('caption-v1')).toBeInTheDocument()
    const calls = (fetch as unknown as { mock: { calls: [RequestInfo | URL, RequestInit?][] } }).mock.calls
    expect(calls.some(([url]) => String(url).includes('/media/captioned-image/intelligence'))).toBe(true)
    expect(calls.some(([url]) => String(url) === '/track/open')).toBe(false)
  })

  describe('indexer phase-aware banner (M-8/S-2)', () => {
    it('does not show a banner when indexer is idle', async () => {
      MockWebSocket.pendingMessage = idleUpdate
      renderPage()
      await waitFor(() => expect(screen.getByPlaceholderText(/describe what you're looking for/i)).toBeTruthy())
      expect(screen.queryByText(/indexing in progress/i)).toBeNull()
      expect(screen.queryByText(/finalizing index/i)).toBeNull()
    })

    it('pre-export phases: search works — banner says results reflect the pre-run library', async () => {
      MockWebSocket.pendingMessage = runningUpdate
      renderPage()
      await waitFor(() =>
        expect(screen.getByText(/indexing in progress — results reflect your library before this run/i)).toBeTruthy()
      )
      // The pre-S-2 "search is temporarily unavailable" claim is now false
      // during the long tail of a run and must never come back.
      expect(screen.queryByText(/temporarily unavailable/i)).toBeNull()
      expect(screen.queryByText(/database is locked/i)).toBeNull()
    })

    it('exporting phase: banner flips to the finalizing message', async () => {
      MockWebSocket.pendingMessage = exportingUpdate
      renderPage()
      await waitFor(() =>
        expect(screen.getByText(/finalizing index — search resumes shortly/i)).toBeTruthy()
      )
      expect(screen.queryByText(/indexing in progress/i)).toBeNull()
    })

    it('running without a summary yet defaults to the pre-export message', async () => {
      MockWebSocket.pendingMessage = {
        type: 'update',
        status: { status: 'running', run_id: 'abc', started_at: null, finished_at: null, elapsed_seconds: 1, return_code: null },
        log: [],
      }
      renderPage()
      await waitFor(() =>
        expect(screen.getByText(/indexing in progress/i)).toBeTruthy()
      )
    })
  })
})
