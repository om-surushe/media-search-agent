import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AdapterWorkbenchPage } from './AdapterWorkbenchPage'
import { getSources } from '@/api/indexer'

vi.mock('@/api/indexer', () => ({ getSources: vi.fn() }))

describe('AdapterWorkbenchPage', () => {
  beforeEach(() => {
    vi.mocked(getSources).mockResolvedValue([{ name: 'sample', path: '/tmp/sample', display_path: '', enabled: true, read_only: true, description: '' }])
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true,
      json: async () => url.endsWith('/adapters')
        ? [{ id: 'discovery', number: 1, name: 'Discovery', runnable: true }, { id: 'identity', number: 2, name: 'Identity', runnable: true }, { id: 'metadata', number: 3, name: 'Metadata', runnable: true }]
        : url.includes('/adapters/discovery/run')
          ? { source: 'sample', returned: 1, has_more: false, entries: [{ name: 'photo.jpg', relative_path: 'photo.jpg', extension: '.jpg', size_bytes: 1 }], elapsed_seconds: 0.01 }
          : { relative_path: 'photo.jpg', sha256: 'abc', elapsed_seconds: 0.002 },
    })))
  })

  it('discovers a bounded sample and runs identity across the source without file selection', async () => {
    render(<AdapterWorkbenchPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Run Discovery (25 max)' }))
    expect(await screen.findByText(/1 files sampled/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Sample file')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run Identity on whole folder' }))
    await waitFor(() => expect(screen.getByText(/Completed in 0.002s/)).toBeInTheDocument())
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(expect.stringContaining('/adapters/identity/run?source_name=sample'), { method: 'POST' })
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).not.toContain('relative_path=')
    fireEvent.click(screen.getByRole('button', { name: 'Run Metadata on whole folder' }))
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining('/adapters/metadata/run?source_name=sample'), { method: 'POST' },
    ))
    expect(String(vi.mocked(fetch).mock.calls.at(-1)?.[0])).not.toContain('relative_path=')
  })
})
