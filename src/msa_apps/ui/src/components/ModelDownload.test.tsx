import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ModelDownload } from './ModelDownload'
import { fetchSetupJob, retrySetup } from '../api/setup'
import type { SetupJobResponse } from '../api/setup'

vi.mock('../api/setup', () => ({
  fetchSetupJob: vi.fn(),
  retrySetup: vi.fn(),
}))

function jobResponse(overrides: Partial<SetupJobResponse> = {}): SetupJobResponse {
  return {
    ready: false,
    read_only_mode: false,
    job: {
      version: 1,
      id: 'setup-job-1',
      status: 'running',
      attempt: 1,
      created_at: 1,
      updated_at: 1,
      downloaded_bytes: 512 * 1024 * 1024,
      total_bytes: 2 * 1024 ** 3,
      progress_percent: 25,
      bytes_per_second: 300_000,
      eta_seconds: 1800,
      models: {},
    },
    ...overrides,
  }
}

function renderDownload(onReady = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <ModelDownload onReady={onReady} />
    </QueryClientProvider>,
  )
  return onReady
}

afterEach(() => vi.resetAllMocks())

describe('ModelDownload', () => {
  it('shows persistent job progress and estimated time', async () => {
    vi.mocked(fetchSetupJob).mockResolvedValue(jobResponse())
    renderDownload()

    expect(await screen.findByText('About 30 minutes remaining')).toBeInTheDocument()
    expect(screen.getByText('512 MB of 2.0 GB')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
    expect(fetchSetupJob).toHaveBeenCalled()
  })

  it('continues into the app when the persisted job is complete and ready', async () => {
    vi.mocked(fetchSetupJob).mockResolvedValue(jobResponse({
      ready: true,
      job: { ...jobResponse().job!, status: 'completed', progress_percent: 100, eta_seconds: 0 },
    }))
    const onReady = renderDownload()
    await waitFor(() => expect(onReady).toHaveBeenCalledTimes(1))
  })

  it('offers resume for a failed job and retries the same job', async () => {
    vi.mocked(fetchSetupJob).mockResolvedValue(jobResponse({
      job: { ...jobResponse().job!, status: 'failed' },
    }))
    vi.mocked(retrySetup).mockResolvedValue(undefined)
    renderDownload()

    await userEvent.click(await screen.findByRole('button', { name: 'Resume setup' }))
    expect(retrySetup).toHaveBeenCalledTimes(1)
  })
})
