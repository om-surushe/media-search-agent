export interface SearchFilters {
  people?: string[]
  place?: string[]
  tags?: string[]
  media_type?: 'image' | 'video' | null
  date_from?: string
  date_to?: string
  min_duration?: number
  max_duration?: number
}

export interface SearchItem {
  id: string
  path: string | null
  thumbnail: string | null
  score: number | null
  raw_similarity_score?: number | null
  similarity_score?: number | null
  person_boost?: number | null
  person_multiplier?: number | null
  expansion_boost?: number | null
  expansion_multiplier?: number | null
  tags: string[] | null
  type: 'video' | null
  timestamp: number | null
  shot_id: number | null
  date: string | null
  gps_lat: number | null
  gps_lon: number | null
  place: string | null
  caption_excerpt?: string | null
  why: string | null
}

export interface SearchResponse {
  results: SearchItem[]
  search_id?: string  // correlates a later /track/open back to this search (ADR-009)
}

export interface MediaItem {
  id: string
  path: string
  date: string | null
  type: 'image' | 'video'
  duration: number | null
  gps_lat: number | null
  gps_lon: number | null
  place: string | null
  tags?: string[] | null
}

export interface MediaListResponse {
  items: MediaItem[]
  count: number
  limit: number
  offset: number
}

export interface VideoShotKeyframe {
  kf_index: number
  timestamp: number
  tags: string[]
  gps_lat: number | null
  gps_lon: number | null
  gps_alt: number | null
  gps_datetime_utc: string | null
  gps_fix: number | null
  gps_source: string | null
  place: string | null
}

export interface VideoShot {
  shot_index: number
  t_start: number
  t_end: number
  duration: number
  is_synthetic: boolean
  keyframes: VideoShotKeyframe[]
}

export interface VideoShotsResponse {
  video_id: string
  path: string
  total_duration: number | null
  shots: VideoShot[]
}

export interface FaceOnMedia {
  face_id: string
  bbox: [number, number, number, number]
  confidence: number
  person_id: string | null
  person_name: string | null
  gender: string | null
  age: number | null
  shot_index: number | null
  kf_index: number | null
}

export interface MediaFacesResponse {
  media_id: string
  faces: FaceOnMedia[]
}

export interface EmbeddingInfo {
  present: boolean
  count: number
  dimensions: number | null
  model: string | null
  created_at: string | null
}

export interface PipelineState {
  pipeline: 'face_detection' | 'object_detection'
  status: 'disabled' | 'not_processed' | 'pending' | 'completed' | 'failed' | 'unsupported'
  evidence: 'recorded' | 'legacy_flag' | 'current_config'
  configured_enabled: boolean
  model_name: string | null
  model_revision: string | null
  started_at: string | null
  completed_at: string | null
  error_type: string | null
}

export interface AssetIntelligence {
  media: {
    id: string; type: 'image' | 'video' | 'unknown'; mime: string | null
    filename: string | null; source_name: string | null; source_folder: string | null
    path: string | null; size_bytes: number | null; width: number | null; height: number | null
    duration: number | null; captured_at: string | null; added_at: string | null
    filesystem_mtime: string | null; camera: string | null; lens: string | null
    gps_lat: number | null; gps_lon: number | null; place: string | null
    gps_processed: boolean | null; gps_data_mode: string | null; gps_sensitive: boolean
    hash_blake3: string | null
    fingerprints: Array<{ source_name: string; relative_path: string; size_bytes: number; filesystem_mtime: string }>
  }
  descriptions: {
    image_caption: { status: string; text: string | null; model_name: string | null }
    image_captions?: Array<{
      caption: string
      model_id: string
      prompt_version: string
      generated_at_utc: string
      status: 'completed' | 'failed'
    }>
    video_summary: { status: string; text: string | null; model_name: string | null }
    scenes: Array<{ start: number; end: number; text: string | null; status: string; model_name: string | null; model_revision?: string | null; generated_at?: string | null }>
  }
  pipeline_status: PipelineState[]
  embeddings: { image: EmbeddingInfo; keyframes: EmbeddingInfo }
  faces: Array<FaceOnMedia & {
    identity_status: string; timestamp: number | null; thumbnail_url: string | null
    embedding: EmbeddingInfo
  }>
  face_count: number
  objects: Array<{ label: string; confidence: number | null; bbox: number[] | null; evidence: string; shot_index: number | null; kf_index: number | null; timestamp: number | null }>
  object_label_count: number
  objects_evidence: string
  stored_tags: string[]
  shots: Array<{ id: number; shot_index: number; start: number; end: number; duration: number; is_synthetic: boolean }>
  total_shots: number
  keyframes: Array<{ id: number; shot_index: number; kf_index: number; timestamp: number; shot_start: number | null; shot_end: number | null; gps_lat: number | null; gps_lon: number | null; gps_alt: number | null; gps_datetime_utc: string | null; gps_fix: number | null; gps_source: string | null; place: string | null; tags: string[]; preview_url: string | null; embedding: EmbeddingInfo }>
  total_keyframes: number
  transcript: {
    status: string; model_name: string | null; model_revision: string | null
    runtime_version: string | null; language: string | null; processed_at: string | null
    error_code: string | null; segments: Array<{ id: number; segment_index: number; start: number; end: number; text: string }>
    total_segments: number
  }
}

export interface MediaFilters {
  media_type?: 'image' | 'video' | null
  date_from?: string
  date_to?: string
  place?: string
  tags?: string[]
  people?: string[]
  people_mode?: 'any' | 'all' | 'only'
  sort_by?: 'date' | 'path'
  sort_order?: 'asc' | 'desc'
}
