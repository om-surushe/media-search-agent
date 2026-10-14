import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KeyframesPage } from './KeyframesPage'

afterEach(() => vi.unstubAllGlobals())

describe('KeyframesPage', () => {
  it('uploads a selected video and displays extracted frames', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        duration: 12.5,
        frames_scanned: 300,
        change_frames: 2,
        slow_change_frames: 1,
        omitted_frames: 0,
        sensitivity_percent: 8,
        adaptive_selection_test: {
          shots_detected: 1,
          midpoint_frames: 1,
          adaptive_frames: 1,
          long_shot_coverage_enabled: false,
          frames: [{
            shot_index: 0,
            timestamp: 4.5,
            reason: 'change',
            change_percent: 10,
            selection_version: 'adaptive-v1',
            image_data_url: 'data:image/jpeg;base64,adaptive',
          }],
          error: null,
        },
        frame_cache_test: {
          selected_frames: 1,
          tested_frames: 1,
          cache_reuse_hits: 1,
          frames: [{
            requested_timestamp: 6.25,
            actual_timestamp: 6.24,
            frame_id: '0123456789abcdef0123456789abcdef',
            checksum_sha256: 'a'.repeat(64),
            reused: true,
            error: null,
          }],
          error: null,
        },
        frames: [{
          timestamp: 6.25,
          change_percent: 12.5,
          reason: 'change',
          image_data_url: 'data:image/jpeg;base64,frame',
        }],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<KeyframesPage />)

    await user.upload(
      screen.getByLabelText('Choose a video'),
      new File(['video'], 'holiday.mp4', { type: 'video/mp4' }),
    )
    await user.click(screen.getByRole('button', { name: 'Show changing frames' }))

    expect(fetchMock).toHaveBeenCalledWith(
      '/video-keyframes/preview?extension=.mp4&sensitivity_percent=8&test_shared_frame_cache=true&test_adaptive_selection=false&test_long_shot_coverage=false',
      expect.objectContaining({ method: 'POST', body: expect.any(File) }),
    )
    expect(await screen.findByRole('img', { name: 'Frame at 6.3 seconds' })).toHaveAttribute(
      'src',
      'data:image/jpeg;base64,frame',
    )
    expect(screen.getByText(/1 frame shown · 12.5s · scanned 300 source frames · 2 change-triggered · 1 gradual-change/)).toBeInTheDocument()
    expect(screen.getByText(/second pass reused 1 cached rendition/)).toBeInTheDocument()
    expect(screen.getByText(/0123456789abcdef · cache hit/)).toBeInTheDocument()

    await user.click(screen.getByLabelText(/Compare opt-in adaptive selection/))
    await user.click(screen.getByRole('button', { name: 'Show changing frames' }))
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/video-keyframes/preview?extension=.mp4&sensitivity_percent=8&test_shared_frame_cache=true&test_adaptive_selection=true&test_long_shot_coverage=false',
      expect.objectContaining({ method: 'POST', body: expect.any(File) }),
    )
    expect(screen.getByText(/1 midpoint fallback frames · 1 additional adaptive candidates/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Adaptive candidate from shot 1 at 4.5 seconds' })).toHaveAttribute(
      'src', 'data:image/jpeg;base64,adaptive',
    )
  })
})
