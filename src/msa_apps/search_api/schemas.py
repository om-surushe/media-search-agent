from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
class SearchFilters(BaseModel):
    people: Optional[List[str]] = None
    place: Optional[List[str]] = None
    tags: Optional[List[str]] = None  # Object/scene detection tags
    user_tags: Optional[List[str]] = Field(default=None, max_length=50)  # User-authored tags
    media_type: Optional[str] = None  # "image", "video", or None for all
    date_from: Optional[str] = None  # YYYY-MM-DD
    date_to: Optional[str] = None
    # Video-specific filters
    timestamp_range: Optional[List[float]] = None  # [start_seconds, end_seconds] within video
    min_duration: Optional[float] = None  # Minimum video duration in seconds
    max_duration: Optional[float] = None  # Maximum video duration in seconds
class SearchRequest(BaseModel):
    q: str
    filters: Optional[SearchFilters] = None
class VideoSceneSearchMatch(BaseModel):
    keyframe_id: int
    timestamp: float
    caption_excerpt: str


class SearchItem(BaseModel):
    id: str
    path: str | None
    thumbnail: str | None
    score: Optional[float] = None  # Semantic similarity score from Qdrant (0–1)
    raw_similarity_score: Optional[float] = None
    similarity_score: Optional[float] = None
    person_boost: Optional[float] = None
    person_multiplier: Optional[float] = None
    expansion_boost: Optional[float] = None
    expansion_multiplier: Optional[float] = None
    tags: Optional[List[str]] = None  # Object/scene detection tags
    user_tags: Optional[List[str]] = None  # User-authored tags
    type: Optional[str] = None  # "video" or None for images
    timestamp: Optional[float] = None  # Video: seek position in seconds
    shot_id: Optional[int] = None  # Video: shot index
    date: Optional[str] = None  # ISO format timestamp
    gps_lat: Optional[float] = None  # EXIF latitude (decimal degrees)
    gps_lon: Optional[float] = None  # EXIF longitude (decimal degrees)
    place: Optional[str] = None  # Human-readable place (e.g., "San Jose, California, US")
    caption_excerpt: Optional[str] = None  # Present when stored caption text matched the query
    scene_timestamp: Optional[float] = None
    scene_matches: Optional[List[VideoSceneSearchMatch]] = None
    why: str | None
class SearchResponse(BaseModel):
    results: List[SearchItem]
    search_id: Optional[str] = None  # correlates opens back to this search (ADR-009)
    semantic_search_available: bool = True
    semantic_search_message: str | None = None

class TranscriptSearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=512)
    limit: int = Field(default=20, ge=1, le=100)

class TranscriptSegmentMatch(BaseModel):
    start: float
    end: float
    text: str

class TranscriptVideoMatch(BaseModel):
    media_id: str
    path: str
    status: str
    language: Optional[str] = None
    model: str
    revision: str
    segments: List[TranscriptSegmentMatch]

class TranscriptSearchResponse(BaseModel):
    results: List[TranscriptVideoMatch]

class TrackOpenRequest(BaseModel):
    search_id: str
    media_id: str

class MediaTagsRequest(BaseModel):
    tags: List[str] = Field(default_factory=list, max_length=50)

class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)

class CollectionMediaRequest(BaseModel):
    media_ids: List[str] = Field(min_length=1, max_length=100)

class KeyframeInfo(BaseModel):
    kf_index: int
    timestamp: float
    tags: List[str]
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_alt: Optional[float] = None
    gps_datetime_utc: Optional[str] = None
    gps_fix: Optional[int] = None
    gps_source: Optional[str] = None
    place: Optional[str] = None

class ShotInfo(BaseModel):
    shot_index: int
    t_start: float  # seconds
    t_end: float    # seconds
    duration: float  # seconds
    is_synthetic: bool
    keyframes: List[KeyframeInfo]

class VideoShotsResponse(BaseModel):
    video_id: str
    path: str
    total_duration: Optional[float] = None
    shots: List[ShotInfo]

# Face search schemas
class FaceSearchRequest(BaseModel):
    face_id: str
    top_k: int = 20

class FaceSearchMatch(BaseModel):
    face_id: str
    score: float
    media_id: Optional[str] = None
    path: Optional[str] = None
    person_id: Optional[str] = None
    person_name: Optional[str] = None
    shot_index: Optional[int] = None
    kf_index: Optional[int] = None

class FaceSearchResponse(BaseModel):
    matches: List[FaceSearchMatch]

# Face suggestions (for labeling assistance)
class PersonSuggestion(BaseModel):
    person_id: str
    person_name: str
    score: float
    face_count: int  # number of similar faces for this person

class FaceSuggestionsResponse(BaseModel):
    face_id: str
    suggestions: List[PersonSuggestion]

# People and labeling schemas
class PersonOut(BaseModel):
    person_id: str
    name: str
    face_count: Optional[int] = None
    thumbnail: Optional[str] = None

class PeopleListResponse(BaseModel):
    people: List[PersonOut]

class PersonCreate(BaseModel):
    name: str

class PersonRename(BaseModel):
    name: str

class MergeRequest(BaseModel):
    source_id: str

class FaceLabelRequest(BaseModel):
    person_id: Optional[str] = None
    name: Optional[str] = None  # If provided without person_id, create person and assign

class BulkLabelRequest(BaseModel):
    face_ids: List[str]
    person_id: Optional[str] = None  # Optional; either person_id or name must be provided
    name: Optional[str] = None       # Create new person if person_id not given

# Batch face suggestions schemas
class BatchFaceSuggestionsRequest(BaseModel):
    face_ids: List[str]
    top_k: int = 5

class BatchFaceSuggestionItem(BaseModel):
    face_id: str
    suggestions: List[PersonSuggestion]

class BatchFaceSuggestionsResponse(BaseModel):
    results: Dict[str, BatchFaceSuggestionItem]
    missing: List[str] = []


PipelineStatus = Literal[
    "disabled", "not_processed", "pending", "completed", "failed", "unsupported", "unknown"
]


class PipelineStateOut(BaseModel):
    pipeline: str
    status: PipelineStatus
    evidence: Literal["recorded", "legacy_flag", "current_config", "unknown"]
    configured_enabled: Optional[bool] = None
    model_name: Optional[str] = None
    model_revision: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_type: Optional[str] = None


class EmbeddingInfo(BaseModel):
    present: bool
    count: int = 0
    dimensions: Optional[int] = None
    model: Optional[str] = None
    created_at: Optional[str] = None


class FingerprintInfo(BaseModel):
    source_name: str
    relative_path: str
    size_bytes: int
    filesystem_mtime: Optional[str] = None


class AssetMediaInfo(BaseModel):
    id: str
    type: Literal["image", "video", "unknown"]
    mime: Optional[str] = None
    filename: Optional[str] = None
    source_name: Optional[str] = None
    source_folder: Optional[str] = None
    path: Optional[str] = None
    size_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    frame_rate: Optional[float] = None
    captured_at: Optional[str] = None
    added_at: Optional[str] = None
    filesystem_mtime: Optional[str] = None
    camera: Optional[str] = None
    lens: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    place: Optional[str] = None
    gps_processed: Optional[bool] = None
    gps_data_mode: Optional[str] = None
    gps_sensitive: bool = True
    hash_blake3: Optional[str] = None
    fingerprints: List[FingerprintInfo] = Field(default_factory=list)


class FaceIntelligenceOut(BaseModel):
    face_id: str
    bbox: List[float]
    confidence: Optional[float] = None
    person_id: Optional[str] = None
    person_name: Optional[str] = None
    identity_status: Literal["known", "unknown"]
    gender: Optional[str] = None
    age: Optional[int] = None
    shot_index: Optional[int] = None
    kf_index: Optional[int] = None
    timestamp: Optional[float] = None
    thumbnail_url: Optional[str] = None
    embedding: EmbeddingInfo


class ObjectLabelOut(BaseModel):
    label: str
    confidence: Optional[float] = None
    bbox: Optional[List[float]] = None
    shot_index: Optional[int] = None
    kf_index: Optional[int] = None
    timestamp: Optional[float] = None
    evidence: Literal["stored_label_only"] = "stored_label_only"


class VideoKeyframeOut(BaseModel):
    id: int
    shot_index: int
    kf_index: int
    timestamp: float
    shot_start: float
    shot_end: float
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_alt: Optional[float] = None
    gps_datetime_utc: Optional[str] = None
    gps_fix: Optional[int] = None
    gps_source: Optional[str] = None
    place: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    preview_url: Optional[str] = None
    embedding: EmbeddingInfo


class VideoShotOut(BaseModel):
    id: int
    shot_index: int
    start: float
    end: float
    duration: float
    is_synthetic: bool


class TranscriptSegmentOut(BaseModel):
    id: int
    segment_index: int
    start: float
    end: float
    text: str


class TranscriptInfo(BaseModel):
    status: Literal["transcribed", "no_speech", "unsupported", "failed", "disabled", "not_processed", "unknown"]
    model_name: Optional[str] = None
    model_revision: Optional[str] = None
    runtime_version: Optional[str] = None
    language: Optional[str] = None
    processed_at: Optional[str] = None
    error_code: Optional[str] = None
    segments: List[TranscriptSegmentOut] = Field(default_factory=list)
    total_segments: int = 0
    offset: int = 0
    limit: int = 100


class DescriptionOut(BaseModel):
    status: Literal["not_generated", "available", "unavailable"]
    text: Optional[str] = None
    model_name: Optional[str] = None
    model_revision: Optional[str] = None
    generated_at: Optional[str] = None


class ImageCaptionOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    caption: str
    model_id: str
    prompt_version: str
    generated_at_utc: str
    status: Literal["completed", "failed"]


class VideoSceneCaptionOut(BaseModel):
    video_id: str
    keyframe_id: int
    timestamp: float
    caption: Optional[str] = None
    model_id: str
    prompt_version: str
    generated_at_utc: str
    status: Literal["completed", "failed"]


class SceneDescriptionOut(BaseModel):
    start: float
    end: float
    text: Optional[str] = None
    status: Literal["not_generated", "available", "unavailable"] = "not_generated"
    model_name: Optional[str] = None
    model_revision: Optional[str] = None
    generated_at: Optional[str] = None


class AssetDescriptionsOut(BaseModel):
    image_caption: DescriptionOut
    image_captions: List[ImageCaptionOut] = Field(default_factory=list)
    video_scene_captions: List[VideoSceneCaptionOut] = Field(default_factory=list)
    video_summary: DescriptionOut
    scenes: List[SceneDescriptionOut] = Field(default_factory=list)


class AssetIntelligenceResponse(BaseModel):
    media: AssetMediaInfo
    descriptions: AssetDescriptionsOut
    pipeline_status: List[PipelineStateOut]
    embeddings: Dict[str, EmbeddingInfo]
    faces: List[FaceIntelligenceOut]
    face_count: int
    objects: List[ObjectLabelOut]
    object_label_count: int
    objects_evidence: Literal["stored_label_only", "none", "unknown"]
    stored_tags: List[str] = Field(default_factory=list)
    shots: List[VideoShotOut] = Field(default_factory=list)
    total_shots: int = 0
    keyframes: List[VideoKeyframeOut] = Field(default_factory=list)
    total_keyframes: int = 0
    transcript: TranscriptInfo
