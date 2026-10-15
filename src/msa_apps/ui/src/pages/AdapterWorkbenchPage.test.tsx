import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AdapterWorkbenchPage } from './AdapterWorkbenchPage'
import { getSources } from '@/api/indexer'
import { useSetupWS } from '@/hooks/useSetupWS'

vi.mock('@/api/indexer', () => ({ getSources: vi.fn() }))
vi.mock('@/hooks/useSetupWS', () => ({ useSetupWS: vi.fn() }))

describe('AdapterWorkbenchPage', () => {
  beforeEach(() => {
    vi.mocked(useSetupWS).mockReturnValue({ models: null, complete: false, revision: 0 })
    vi.mocked(getSources).mockResolvedValue([{ name: 'sample', path: '/tmp/sample', display_path: '', enabled: true, read_only: true, description: '' }])
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url.endsWith('/adapters')
        ? [{ id: 'discovery', number: 1, name: 'Discovery', runnable: true }, { id: 'identity', number: 2, name: 'Identity', runnable: true }, { id: 'metadata', number: 3, name: 'Metadata', runnable: true }, { id: 'transcription', number: 4, name: 'Video transcription', runnable: true }, { id: 'image-visual', number: 5, name: 'Image visual processing', runnable: true }, { id: 'video-keyframes', number: 6, name: 'Complete video keyframe processing', runnable: true }]
        : url.includes('/api/setup/status')
          ? { ready: false, models: [] }
          : url.includes('/api/setup/retry')
            ? { status: 'retrying' }
            : url.includes('/adapters/discovery/run')
          ? { source: 'sample', returned: 1, has_more: false, entries: [{ name: 'photo.jpg', relative_path: 'photo.jpg', extension: '.jpg', size_bytes: 1 }], elapsed_seconds: 0.01 }
          : { relative_path: 'photo.jpg', sha256: 'abc', elapsed_seconds: 0.002 },
    })))
  })

  it('discovers a bounded sample and runs identity across the source without file selection', async () => {
    render(<AdapterWorkbenchPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Run Discovery (25 max)' }))
    expect(await screen.findByText(/1 files sampled/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry / verify model setup' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Sample file')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run on every image' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run Identity on whole folder' }))
    await waitFor(() => expect(screen.getByText(/Completed in 0.002s/)).toBeInTheDocument())
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(expect.stringContaining('/adapters/identity/run?source_name=sample'), { method: 'POST' })
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).not.toContain('relative_path=')
    fireEvent.click(screen.getByRole('button', { name: 'Run Metadata on whole folder' }))
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining('/adapters/metadata/run?source_name=sample'), { method: 'POST' },
    ))
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).not.toContain('relative_path=')
    fireEvent.click(screen.getByRole('button', { name: 'Run Video transcription on whole folder' }))
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining('/adapters/transcription/run?source_name=sample'), { method: 'POST' },
    ))
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).not.toContain('relative_path=')
    fireEvent.click(screen.getByRole('button', { name: 'Run on every image' }))
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining('/adapters/image-visual/run?source_name=sample'), { method: 'POST' },
    ))
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).not.toContain('relative_path=')
    fireEvent.click(screen.getByRole('button', { name: 'Run on every video' }))
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining('/adapters/video-keyframes/run?source_name=sample'), { method: 'POST' },
    ))
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).not.toContain('relative_path=')
  })

  it('shows the model loader when Stage 05 is unavailable', async () => {
    vi.mocked(fetch).mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url.endsWith('/adapters')
        ? [{ id: 'image-visual', number: 5, name: 'Image visual processing', runnable: false, reason: 'CLIP weights are not cached.' }]
        : url.includes('/api/setup/status')
          ? { ready: false, models: [{ id: 'clip', label: 'CLIP', size_mb: 1711, present: true, integrity_hint: '', source: 'huggingface.co/example' }] }
          : { status: 'retrying' },
    } as Response))

    vi.mocked(useSetupWS).mockReturnValue({ models: { clip: { status: 'error', error: 'no approved checkpoint found' } }, complete: true, revision: 1 })
    render(<AdapterWorkbenchPage />)
    expect(await screen.findByText('CLIP weights are not cached.')).toBeInTheDocument()
    expect(await screen.findByText(/CLIP: error — no approved checkpoint found/)).toBeInTheDocument()
    vi.mocked(window.confirm).mockClear()
    fireEvent.click(await screen.findByRole('button', { name: 'Download / retry 1 model(s) (~1711 MB)' }))
    expect(window.confirm).not.toHaveBeenCalled()
    expect(await screen.findByText(/Starting model setup \(1 missing, ~1711 MB/)).toBeInTheDocument()
    await waitFor(() => expect(vi.mocked(useSetupWS)).toHaveBeenLastCalledWith(1))
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining('/api/setup/retry'), { method: 'POST' },
    ))
    expect(await screen.findByRole('button', { name: 'Loading models…' })).toBeDisabled()
  })
})
