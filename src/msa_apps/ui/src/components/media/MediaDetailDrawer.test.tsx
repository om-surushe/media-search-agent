import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MediaDetailDrawer } from './MediaDetailDrawer'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

const mockIntelligence = {
  media: { id: 'img-01', type: 'image', mime: 'image/jpeg', filename: 'beach.jpg', source_name: 'fixture', source_folder: 'photos', path: '/photos/beach.jpg', size_bytes: 1024, width: 10, height: 20, duration: null, captured_at: null, added_at: null, filesystem_mtime: null, camera: null, lens: null, gps_lat: null, gps_lon: null, gps_sensitive: false, hash_blake3: null, fingerprints: [] },
  descriptions: { image_caption: { status: 'not_generated', text: null, model_name: null }, image_captions: [], video_summary: { status: 'not_generated', text: null, model_name: null }, scenes: [] },
  pipeline_status: [
    { pipeline: 'face_detection', status: 'disabled', evidence: 'current_config', configured_enabled: false, model_name: null, model_revision: null, started_at: null, completed_at: null, error_type: null },
    { pipeline: 'object_detection', status: 'not_processed', evidence: 'current_config', configured_enabled: true, model_name: null, model_revision: null, started_at: null, completed_at: null, error_type: null },
  ],
  embeddings: { image: { present: true, count: 1, dimensions: 768, model: 'clip', created_at: null }, keyframes: { present: false, count: 0, dimensions: null, model: null, created_at: null } },
  faces: [], face_count: 0, objects: [], object_label_count: 0, objects_evidence: 'none', stored_tags: [], shots: [], total_shots: 0, keyframes: [], total_keyframes: 0,
  transcript: { status: 'disabled', model_name: null, model_revision: null, runtime_version: null, language: null, processed_at: null, error_code: null, segments: [], total_segments: 0 },
}

const videoIntelligence = {
  ...mockIntelligence,
  descriptions: {
    ...mockIntelligence.descriptions,
    video_scene_captions: [{
      video_id: 'vid-01', keyframe_id: 2, timestamp: 36.5,
      caption: 'A person walks beside a parked car.', model_id: 'mlx/smolvlm',
      prompt_version: 'stage4b-video-scene-v1', generated_at_utc: '2026-10-14T10:00:00+00:00',
      status: 'completed' as const,
    }],
  },
  media: { ...mockIntelligence.media, id: 'vid-01', type: 'video', mime: 'video/mp4', filename: 'clip.mp4', duration: 40 },
  keyframes: [
    { id: 1, shot_index: 0, kf_index: 0, timestamp: 2.6, tags: [], place: null },
    { id: 2, shot_index: 1, kf_index: 0, timestamp: 36.5, tags: [], place: null },
  ],
  total_keyframes: 2,
  total_shots: 2,
}

const videoItem = { id: 'vid-01', type: 'video' as const, path: '/videos/clip.mp4' }

const baseItem = {
  id: 'img-01',
  type: 'image' as const,
  date: '2024-03-15T10:30:00',
  place: null as string | null,
  gps_lat: null as number | null,
  gps_lon: null as number | null,
  score: null as number | null,
  tags: null as string[] | null,
  path: '/photos/vacation/beach.jpg',
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const payload = String(input).includes('/intelligence') ? mockIntelligence : { faces: [] }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })
  }))
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    writable: true,
    configurable: true,
  })
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('MediaDetailDrawer', () => {
  it('defers selected keyframe seek until video metadata is ready and stays paused', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(videoIntelligence) })))
    const { container } = wrap(<MediaDetailDrawer item={videoItem} onClose={vi.fn()} />)
    const keyframe = await screen.findByRole('button', { name: /2\.6s · shot 1/ })
    const video = container.querySelector('video')!
    let currentTime = 0
    Object.defineProperty(video, 'readyState', { configurable: true, value: 0 })
    Object.defineProperty(video, 'currentTime', { configurable: true, get: () => currentTime, set: value => { currentTime = value } })
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    const play = vi.spyOn(video, 'play').mockResolvedValue(undefined)

    await userEvent.click(keyframe)
    expect(keyframe).toHaveAttribute('aria-pressed', 'true')
    expect(currentTime).toBe(0)
    expect(pause).toHaveBeenCalled()
    expect(play).not.toHaveBeenCalled()

    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    fireEvent.loadedMetadata(video)
    expect(currentTime).toBe(2.6)
    expect(play).not.toHaveBeenCalled()
  })

  it('re-seeks when the best scene changes for the same video result', async () => {
    const firstItem = {
      ...videoItem, timestamp: 1, scene_timestamp: 6.8,
      scene_matches: [{ keyframe_id: 1, timestamp: 6.8, caption_excerpt: 'pink shirts' }],
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const renderDrawer = (item: typeof firstItem) => (
      <QueryClientProvider client={client}>
        <MemoryRouter><MediaDetailDrawer item={item} onClose={vi.fn()} /></MemoryRouter>
      </QueryClientProvider>
    )
    const { container, rerender } = render(renderDrawer(firstItem))
    const video = container.querySelector('video')!
    let currentTime = 0
    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    Object.defineProperty(video, 'currentTime', { configurable: true, get: () => currentTime, set: value => { currentTime = value } })
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    fireEvent.loadedMetadata(video)
    expect(currentTime).toBe(6.8)

    rerender(renderDrawer({
      ...firstItem, scene_timestamp: 18.2,
      scene_matches: [{ keyframe_id: 2, timestamp: 18.2, caption_excerpt: 'pink shirts' }],
    }))

    expect(currentTime).toBe(18.2)
    expect(pause).toHaveBeenCalled()
  })

  it('switches keyframes without reloading and preserves native playback controls', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(videoIntelligence) })))
    const { container } = wrap(<MediaDetailDrawer item={videoItem} onClose={vi.fn()} />)
    const first = await screen.findByRole('button', { name: /2\.6s · shot 1/ })
    const second = screen.getByRole('button', { name: /36\.5s · shot 2/ })
    const video = container.querySelector('video')!
    let currentTime = 0
    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    Object.defineProperty(video, 'currentTime', { configurable: true, get: () => currentTime, set: value => { currentTime = value } })
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    const play = vi.spyOn(video, 'play').mockResolvedValue(undefined)
    const load = vi.spyOn(video, 'load').mockImplementation(() => {})
    const src = video.getAttribute('src')

    await userEvent.click(first)
    expect(currentTime).toBe(2.6)
    expect(first).toHaveAttribute('aria-pressed', 'true')
    expect(pause).toHaveBeenCalled()
    expect(play).not.toHaveBeenCalled()
    await userEvent.click(second)
    expect(currentTime).toBe(36.5)
    expect(second).toHaveAttribute('aria-pressed', 'true')
    expect(first).toHaveAttribute('aria-pressed', 'false')
    expect(video.controls).toBe(true)
    expect(video.getAttribute('src')).toBe(src)
    expect(load).not.toHaveBeenCalled()
    expect(play).not.toHaveBeenCalled()

    await video.play()
    expect(play).toHaveBeenCalledOnce()
    expect(currentTime).toBe(36.5)
  })

  it('shows scene captions with provenance and seeks to their paused keyframe', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(videoIntelligence) })))
    const { container } = wrap(<MediaDetailDrawer item={videoItem} onClose={vi.fn()} />)
    expect(await screen.findByText('Visual Scene Descriptions')).toBeInTheDocument()
    expect(screen.getByText('A person walks beside a parked car.')).toBeInTheDocument()
    expect(screen.getByText(/mlx\/smolvlm · stage4b-video-scene-v1/)).toBeInTheDocument()
    const seek = screen.getByRole('button', { name: 'Seek to scene at 36.5 seconds' })
    const video = container.querySelector('video')!
    let currentTime = 0
    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    Object.defineProperty(video, 'currentTime', { configurable: true, get: () => currentTime, set: value => { currentTime = value } })
    const pause = vi.spyOn(video, 'pause').mockImplementation(() => {})
    const play = vi.spyOn(video, 'play').mockResolvedValue(undefined)

    await userEvent.click(seek)
    expect(currentTime).toBe(36.5)
    expect(seek).toHaveAttribute('aria-pressed', 'true')
    expect(pause).toHaveBeenCalled()
    expect(play).not.toHaveBeenCalled()
  })

  it('shows an empty visual scene state for videos without captions', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        ...videoIntelligence,
        descriptions: { ...videoIntelligence.descriptions, video_scene_captions: [] },
      }),
    })))
    wrap(<MediaDetailDrawer item={videoItem} onClose={vi.fn()} />)
    expect(await screen.findByText('No visual scene descriptions available.')).toBeInTheDocument()
  })

  it('shows an alert when seeking the selected keyframe throws', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(videoIntelligence) })))
    const { container } = wrap(<MediaDetailDrawer item={videoItem} onClose={vi.fn()} />)
    const keyframe = await screen.findByRole('button', { name: /2\.6s · shot 1/ })
    const video = container.querySelector('video')!
    Object.defineProperty(video, 'readyState', { configurable: true, value: 1 })
    Object.defineProperty(video, 'currentTime', { configurable: true, set: () => { throw new Error('seek failed') } })
    vi.spyOn(video, 'pause').mockImplementation(() => {})

    await userEvent.click(keyframe)
    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to seek to this video timestamp.')
  })

  it('shows explicit detector states and metadata from the inspector API', async () => {
    wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
    expect(await screen.findByText('Object detection')).toBeInTheDocument()
    expect(screen.getByText('not processed')).toBeInTheDocument()
    expect(screen.getByText('Image caption: not generated yet.')).toBeInTheDocument()
  })

  it('shows every stored caption with provenance and keeps other inspector sections read-only', async () => {
    const payload = {
      ...mockIntelligence,
      descriptions: {
        ...mockIntelligence.descriptions,
        image_caption: { status: 'available', text: 'Newest caption.', model_name: 'mlx/model-b' },
        image_captions: [
          { caption: 'A dog is behind a fence.', model_id: 'mlx/model-a', prompt_version: 'prompt-v1', generated_at_utc: '2026-10-14T10:00:00+00:00', status: 'completed' as const },
          { caption: 'Newest caption.', model_id: 'mlx/model-b', prompt_version: 'prompt-v2', generated_at_utc: '2026-10-14T10:01:00+00:00', status: 'completed' as const },
        ],
      },
      faces: [{ face_id: 'img-01:f0', bbox: [0.1, 0.2, 0.3, 0.4], confidence: 0.99, person_id: null, person_name: null, identity_status: 'unknown', gender: null, age: null, shot_index: null, kf_index: null, timestamp: null, thumbnail_url: null, embedding: { present: false, count: 0, dimensions: null, model: null, created_at: null } }],
      face_count: 1,
      objects: [{ label: 'dog', confidence: 0.95, bbox: null, evidence: 'stored_label_only', shot_index: null, kf_index: null, timestamp: null }],
      object_label_count: 1,
      objects_evidence: 'stored_label_only',
      transcript: { status: 'transcribed', model_name: 'whisper-local', model_revision: null, runtime_version: null, language: 'en', processed_at: null, error_code: null, segments: [{ id: 1, segment_index: 0, start: 0, end: 1, text: 'existing transcript' }], total_segments: 1 },
    }
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })))
    wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)

    expect(await screen.findByText('A dog is behind a fence.')).toBeInTheDocument()
    expect(screen.getByText('Newest caption.')).toBeInTheDocument()
    expect(screen.getByText('mlx/model-a')).toBeInTheDocument()
    expect(screen.getByText('prompt-v2')).toBeInTheDocument()
    expect(screen.getAllByText('completed')).toHaveLength(2)
    expect(screen.getAllByText(/2026/).length).toBeGreaterThan(0)
    expect(screen.getByText('dog · 95.0%')).toBeInTheDocument()
    expect(screen.getByText('Face detections · 1')).toBeInTheDocument()
    expect(screen.getByText('existing transcript')).toBeInTheDocument()
    const calls = (fetch as unknown as { mock: { calls: [RequestInfo | URL, RequestInit?][] } }).mock.calls
    expect(calls.every(([, options]) => !options?.method || options.method === 'GET')).toBe(true)
  })

  it('shows the empty AI Description state when no captions are stored', async () => {
    wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
    expect(await screen.findByText('No AI description generated yet.')).toBeInTheDocument()
  })

  it('keeps the page interactive on desktop and uses a full-screen mobile modal', () => {
    const { container } = wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
    const [backdrop, panel] = Array.from(container.querySelectorAll('div.fixed'))
    expect(backdrop.className).toContain('md:hidden')
    expect(panel.className).toContain('w-full')
    expect(panel.className).toContain('md:w-[min(42rem,calc(100vw-4rem))]')
  })

  it('renders successful detections returned by the inspector', async () => {
    const payload = {
      ...mockIntelligence,
      pipeline_status: mockIntelligence.pipeline_status.map(stage => ({ ...stage, status: 'completed', configured_enabled: true })),
      faces: [{ face_id: 'img-01:f0', bbox: [0.1, 0.2, 0.3, 0.4], confidence: 0.99, person_id: null, person_name: null, identity_status: 'unknown', gender: null, age: null, shot_index: null, kf_index: null, timestamp: null, thumbnail_url: null, embedding: { present: true, count: 1, dimensions: 512, model: 'facenet', created_at: null } }],
      face_count: 1,
      objects: [{ label: 'dog', confidence: 0.95, bbox: null, evidence: 'stored_label_only', shot_index: null, kf_index: null, timestamp: null }],
      object_label_count: 1,
      objects_evidence: 'stored_label_only',
    }
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })))
    wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
    expect(await screen.findByText(/dog/)).toBeInTheDocument()
    expect(screen.getByText('Face detections · 1')).toBeInTheDocument()
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0)
  })

  it('shows loading and API error states', async () => {
    let resolveRequest!: (value: { ok: boolean; json: () => Promise<unknown> }) => void
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      if (String(input).includes('/intelligence')) return new Promise(resolve => { resolveRequest = resolve })
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    }))
    wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
    expect(await screen.findByText('Loading asset metadata…')).toBeInTheDocument()
    resolveRequest({ ok: false, json: () => Promise.resolve({}) })
    expect(await screen.findByRole('alert')).toHaveTextContent('Asset metadata unavailable.')
  })

  it('refreshes inspector data when switching assets', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const id = String(input).match(/media\/([^/]+)\/intelligence/)?.[1]
      const payload = { ...mockIntelligence, media: { ...mockIntelligence.media, id, filename: `${id}.jpg` } }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })
    }))
    const tree = (item: typeof baseItem) => <QueryClientProvider client={qc}><MemoryRouter><MediaDetailDrawer item={item} onClose={vi.fn()} /></MemoryRouter></QueryClientProvider>
    const { rerender } = render(tree(baseItem))
    expect(await screen.findByText('img-01.jpg')).toBeInTheDocument()
    const nextItem = { ...baseItem, id: 'img-02', path: '/photos/img-02.jpg' }
    rerender(tree(nextItem))
    expect(await screen.findByText('img-02.jpg')).toBeInTheDocument()
  })

  it('does not render media content when item is null', () => {
    wrap(<MediaDetailDrawer item={null} onClose={vi.fn()} />)
    expect(screen.queryByRole('img')).toBeNull()
  })

  describe('open tracking (/track/open)', () => {
    it('posts the open as a label when opened from a search', async () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} searchId="srch-123" />)
      await waitFor(() => {
        expect(fetch).toHaveBeenCalledWith('/track/open', expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ search_id: 'srch-123', media_id: 'img-01' }),
        }))
      })
    })

    it('does not post /track/open when there is no search_id', async () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
      // Wait for effects + the faces query to flush, so a late post would be caught.
      await waitFor(() => expect(fetch).toHaveBeenCalled())  // the faces request
      await new Promise(r => setTimeout(r, 0))
      const urls = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.map(c => c[0])
      expect(urls).not.toContain('/track/open')
    })

    it('tracks once per opened item even if searchId changes while it stays open', async () => {
      const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
      const view = (sid: string) => (
        <QueryClientProvider client={qc}>
          <MemoryRouter>
            <MediaDetailDrawer item={baseItem} onClose={vi.fn()} searchId={sid} />
          </MemoryRouter>
        </QueryClientProvider>
      )
      const { rerender } = render(view('srch-1'))
      await waitFor(() =>
        expect(fetch).toHaveBeenCalledWith('/track/open', expect.objectContaining({ method: 'POST' }))
      )
      // Same item stays open but the search refetches under a new id — must NOT re-post.
      rerender(view('srch-2'))
      await new Promise(r => setTimeout(r, 0))
      const trackPosts = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
        .filter(c => c[0] === '/track/open')
      expect(trackPosts).toHaveLength(1)
      expect(trackPosts[0][1]).toMatchObject({
        body: JSON.stringify({ search_id: 'srch-1', media_id: 'img-01' }),
      })
    })
  })

  describe('PathRow', () => {
    it('shows only the filename', () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
      expect(screen.getByText('beach.jpg')).toBeInTheDocument()
    })

    it('renders the full path in the hover tooltip', () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
      expect(screen.getByText('/photos/vacation/beach.jpg')).toBeInTheDocument()
    })

    it('copies full path to clipboard when copy button is clicked', async () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
      await userEvent.click(screen.getByTitle('/photos/vacation/beach.jpg'))
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith('/photos/vacation/beach.jpg')
    })

    it('handles paths with backslashes (Windows)', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, path: 'C:\\Users\\Photos\\beach.jpg' }} onClose={vi.fn()} />)
      expect(screen.getByText('beach.jpg')).toBeInTheDocument()
    })
  })

  describe('date row', () => {
    it('shows a formatted date when date is present', () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
      expect(screen.getByText(/2024/)).toBeInTheDocument()
    })

    it('hides date row when date is null', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, date: null }} onClose={vi.fn()} />)
      expect(screen.queryByText(/2024/)).toBeNull()
    })
  })

  describe('GPS / place row', () => {
    it('renders a Google Maps link when coordinates are present', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, gps_lat: 37.77, gps_lon: -122.42 }} onClose={vi.fn()} />)
      const link = screen.getByTitle('Open in Google Maps')
      expect(link).toHaveAttribute('href', expect.stringContaining('37.77'))
      expect(link).toHaveAttribute('href', expect.stringContaining('-122.42'))
      expect(link).toHaveAttribute('target', '_blank')
    })

    it('link URL uses google.com/maps', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, gps_lat: 51.5, gps_lon: -0.1 }} onClose={vi.fn()} />)
      const link = screen.getByTitle('Open in Google Maps')
      expect(link).toHaveAttribute('href', expect.stringContaining('google.com/maps'))
    })

    it('shows place name as plain text (no link) when only place is set', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, place: 'San Francisco' }} onClose={vi.fn()} />)
      expect(screen.getByText('San Francisco')).toBeInTheDocument()
      expect(screen.queryByRole('link', { name: /google maps/i })).toBeNull()
    })

    it('hides location row when neither place nor GPS is present', () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
      expect(screen.queryByRole('link', { name: /google maps/i })).toBeNull()
    })
  })

  describe('tags', () => {
    it('shows tag chips when tags are present', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, tags: ['cat', 'person'] }} onClose={vi.fn()} />)
      expect(screen.getByText('cat')).toBeInTheDocument()
      expect(screen.getByText('person')).toBeInTheDocument()
    })

    it('hides tags section when tags is null', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, tags: null }} onClose={vi.fn()} />)
      expect(screen.queryByText('cat')).toBeNull()
    })

    it('hides tags section when tags is empty array', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, tags: [] }} onClose={vi.fn()} />)
      expect(screen.queryByText('cat')).toBeNull()
    })
  })

  describe('debug why field', () => {
    it('does not render the why string', () => {
      const item = { ...baseItem, why: "['Alice'] | None | src=img score=0.91" }
      wrap(<MediaDetailDrawer item={item} onClose={vi.fn()} />)
      expect(screen.queryByText(/src=img/)).toBeNull()
    })
  })

  describe('score bar', () => {
    it('shows score percentage when score is present', () => {
      wrap(<MediaDetailDrawer item={{ ...baseItem, score: 0.85 }} onClose={vi.fn()} />)
      expect(screen.getByText('85% match')).toBeInTheDocument()
    })

    it('hides score bar when score is null', () => {
      wrap(<MediaDetailDrawer item={baseItem} onClose={vi.fn()} />)
      expect(screen.queryByText(/% match/)).toBeNull()
    })
  })
})
