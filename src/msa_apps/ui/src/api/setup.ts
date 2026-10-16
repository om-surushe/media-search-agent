export type ModelState = 'pending' | 'downloading' | 'verifying' | 'done' | 'error'

export interface ModelInfo {
  id: string
  label: string
  size_mb: number
  present: boolean
  integrity_hint: string
  // Download origin host + path (e.g. "huggingface.co/PekingU/rtdetr_r18vd").
  // Shown on the first-launch setup page as a trust signal so users can see
  // bytes are coming from a known model host rather than a random URL.
  source: string
}

export interface SetupStatus {
  ready: boolean
  models: ModelInfo[]
  read_only_mode?: boolean
}

export interface ModelDownloadState {
  status: ModelState
  error: string | null
  downloaded_bytes?: number
  total_bytes?: number
  filename?: string | null
}

export interface SetupWSUpdate {
  type: 'update' | 'complete'
  models: Record<string, ModelDownloadState>
}

export type SetupJobState = 'pending' | 'running' | 'retrying' | 'completed' | 'failed'

export interface SetupJob {
  version: number
  id: string
  status: SetupJobState
  attempt: number
  created_at: number
  updated_at: number
  downloaded_bytes: number
  total_bytes: number
  progress_percent: number
  bytes_per_second: number | null
  eta_seconds: number | null
  models: Record<string, ModelDownloadState>
}

export interface SetupJobResponse {
  ready: boolean
  job: SetupJob | null
  read_only_mode: boolean
}

import { apiUrl } from '../lib/apiBase'

export async function fetchSetupStatus(): Promise<SetupStatus> {
  const res = await fetch(apiUrl('/api/setup/status'))
  if (!res.ok) throw new Error(`setup/status ${res.status}`)
  return res.json()
}

export async function fetchSetupJob(): Promise<SetupJobResponse> {
  const res = await fetch(apiUrl('/api/setup/job'), { cache: 'no-store' })
  if (!res.ok) throw new Error(`setup/job ${res.status}`)
  return res.json()
}

export async function startSetup(): Promise<void> {
  const res = await fetch(apiUrl('/api/setup/start'), { method: 'POST' })
  if (!res.ok) throw new Error(`setup/start ${res.status}`)
}

export async function retrySetup(): Promise<void> {
  const res = await fetch(apiUrl('/api/setup/retry'), { method: 'POST' })
  if (!res.ok) throw new Error(`setup/retry ${res.status}`)
}

export async function retryCaptioningSetup(): Promise<void> {
  const res = await fetch(apiUrl('/api/setup/captioning/retry'), { method: 'POST' })
  if (!res.ok) throw new Error(`setup/captioning/retry ${res.status}`)
}
