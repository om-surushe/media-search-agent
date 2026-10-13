import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { BrowsePage } from './BrowsePage'

const intelligence = {
  media: {
    id: 'captioned-image', type: 'image', mime: 'image/jpeg', filename: 'dog.jpg',
    source_name: 'fixture', source_folder: 'photos', path: '/tmp/dog.jpg',
    size_bytes: 12, width: 2, height: 2, duration: null, captured_at: null,
    added_at: null, filesystem_mtime: null, camera: null, lens: null,
    gps_lat: null, gps_lon: null, place: null, gps_processed: false,
    gps_data_mode: null, gps_sensitive: false, hash_blake3: null, fingerprints: [],
  },
  descriptions: {
    image_caption: { status: 'available', text: 'A black dog looks through a fence.', model_name: 'mlx/model' },
    image_captions: [{
      caption: 'A black dog looks through a fence.', model_id: 'mlx/model',
      prompt_version: 'caption-v1', generated_at_utc: '2026-10-14T10:00:00+00:00',
      status: 'completed',
    }],
    video_summary: { status: 'not_generated', text: null, model_name: null }, scenes: [],
  },
  pipeline_status: [],
  embeddings: {
    image: { present: false, count: 0, dimensions: null, model: null, created_at: null },
    keyframes: { present: false, count: 0, dimensions: null, model: null, created_at: null },
  },
  faces: [], face_count: 0, objects: [], object_label_count: 0,
  objects_evidence: 'none', stored_tags: [], shots: [], total_shots: 0,
  keyframes: [], total_keyframes: 0,
  transcript: {
    status: 'unsupported', model_name: null, model_revision: null,
    runtime_version: null, language: null, processed_at: null, error_code: null,
    segments: [], total_segments: 0,
  },
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><BrowsePage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class {
    observe() {}
    disconnect() {}
  })
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    const body = url.includes('/intelligence') ? intelligence
      : url.startsWith('/media?') ? {
        items: [{ id: 'captioned-image', path: '/tmp/dog.jpg', type: 'image', date: null, duration: null, gps_lat: null, gps_lon: null, place: null }],
        count: 1, limit: 48, offset: 0,
      }
      : url === '/people' ? { people: [] }
        : url === '/tags' ? [] : {}
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
  }))
})
afterEach(() => vi.unstubAllGlobals())

describe('BrowsePage shared inspector', () => {
  it('opens the shared drawer and displays the stored AI description without write requests', async () => {
    const { container } = renderPage()
    // The card preview is decorative; locate its button by the indexed thumbnail URL.
    await screen.findByRole('button', { name: '' })
    const mediaButton = container.querySelector('button img[src*="captioned-image"]')?.closest('button')
    expect(mediaButton).not.toBeNull()
    fireEvent.click(mediaButton!)

    expect(await screen.findByText('A black dog looks through a fence.')).toBeInTheDocument()
    expect(screen.getByText('mlx/model')).toBeInTheDocument()
    expect(screen.getByText('caption-v1')).toBeInTheDocument()
    const calls = (fetch as unknown as { mock: { calls: [RequestInfo | URL, RequestInit?][] } }).mock.calls
    expect(calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true)
  })
})
