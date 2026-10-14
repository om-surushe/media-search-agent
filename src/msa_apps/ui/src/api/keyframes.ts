import { apiUrl } from '../lib/apiBase'

export interface KeyframePreviewFrame {
  timestamp: number
  change_percent: number
  reason: 'start' | 'change' | 'slow_change'
  image_data_url: string
}

export interface FrameCacheTestFrame {
  requested_timestamp: number
  actual_timestamp: number | null
  frame_id: string | null
  checksum_sha256: string | null
  reused: boolean
  error: string | null
}

export interface FrameCacheTest {
  selected_frames: number
  tested_frames: number
  cache_reuse_hits: number
  frames: FrameCacheTestFrame[]
  error: string | null
}

export interface AdaptiveSelectionTestFrame {
  shot_index: number
  timestamp: number
  reason: string
  change_percent: number
  selection_version: string
  image_data_url: string | null
}

export interface AdaptiveSelectionTest {
  shots_detected: number
  midpoint_frames: number
  adaptive_frames: number
  long_shot_coverage_enabled: boolean
  frames: AdaptiveSelectionTestFrame[]
  error: string | null
}

export interface KeyframePreview {
  duration: number
  frames_scanned: number
  change_frames: number
  slow_change_frames: number
  omitted_frames: number
  sensitivity_percent: number
  frames: KeyframePreviewFrame[]
  frame_cache_test: FrameCacheTest | null
  adaptive_selection_test: AdaptiveSelectionTest | null
}

export async function previewVideoKeyframes(
  file: File,
  sensitivityPercent: number,
  testSharedFrameCache: boolean,
  testAdaptiveSelection: boolean,
  testLongShotCoverage: boolean,
): Promise<KeyframePreview> {
  const extension = file.name.match(/\.[^.]+$/)?.[0]?.toLowerCase() ?? '.mp4'
  const response = await fetch(apiUrl(`/video-keyframes/preview?extension=${encodeURIComponent(extension)}&sensitivity_percent=${sensitivityPercent}&test_shared_frame_cache=${testSharedFrameCache}&test_adaptive_selection=${testAdaptiveSelection}&test_long_shot_coverage=${testLongShotCoverage}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? `Preview failed (${response.status})`)
  }
  return response.json() as Promise<KeyframePreview>
}
