import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CommercialModelCatalog } from './CommercialModelCatalog'

const entry = {
  id: 'clip-vit-b32', task: 'visual_embedding', label: 'CLIP ViT-B/32', publisher: 'OpenAI',
  source: 'openai/clip-vit-base-patch32', revision: 'abc123',
  license_claim: 'MIT (code repository)', license_evidence: 'https://example.test/license',
  clearance: 'review_required' as const, access_note: null, downloadable: true, installed: false,
  path: '/tmp/models/commercial/clip-vit-b32/snapshot', size_bytes: 1000, min_ram_gb: 4,
  hardware_fit: true, recommended_for_task: true, adapter_status: 'evaluation only',
  state: { status: 'pending' as const, error: null, downloaded_bytes: 0, total_bytes: 0, filename: null },
}
const catalog = {
  hardware: { os: 'linux', architecture: 'x86_64', ram_gb: 16, cpu_count: 8, accelerator: 'cpu', hardware_recommendations_are_advisory: true as const },
  models: [entry],
}

function renderCatalog() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><CommercialModelCatalog /></QueryClientProvider>)
}

afterEach(() => vi.unstubAllGlobals())

describe('CommercialModelCatalog', () => {
  it('shows pinned model path, license caveat, and advisory hardware fit', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => catalog }))
    renderCatalog()
    expect(await screen.findByText('CLIP ViT-B/32')).toBeInTheDocument()
    expect(screen.getByText(entry.path)).toBeInTheDocument()
    expect(screen.getByText(/not commercially cleared/i)).toBeInTheDocument()
    expect(screen.getByText(/hardware-fit candidate/i)).toBeInTheDocument()
  })

  it('requires explicit confirmation before requesting an evaluation download', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => catalog })
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn().mockReturnValue(true))
    renderCatalog()
    await userEvent.click(await screen.findByRole('button', { name: 'Download for evaluation' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/models/clip-vit-b32/download',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ confirm_experimental: true }) }),
    ))
  })

  it('shows a determinate transfer bar when byte progress is available', async () => {
    const downloading = {
      ...entry,
      state: { status: 'downloading' as const, error: null, downloaded_bytes: 250, total_bytes: 1000, filename: 'model.safetensors' },
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...catalog, models: [downloading] }),
    }))
    renderCatalog()
    const bar = await screen.findByRole('progressbar', { name: 'CLIP ViT-B/32 download progress' })
    expect(bar).toHaveAttribute('value', '250')
    expect(await screen.findByText(/250 B of 1000 B/)).toBeInTheDocument()
  })
})
