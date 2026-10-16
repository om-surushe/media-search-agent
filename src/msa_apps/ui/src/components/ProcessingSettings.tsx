import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getModelConfig, patchModelConfig, type ModelConfigEditable } from '../api/indexer'

const labelClass = 'text-sm font-medium text-zinc-700 dark:text-zinc-200'
const helpClass = 'mt-1 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400'
const inputClass = 'rounded border border-slate-300 dark:border-zinc-600 bg-white dark:bg-zinc-900 px-2 py-1.5 text-sm text-zinc-800 dark:text-zinc-200'

type PresetId = 'maximum' | 'balanced' | 'fast'

function presetValues(id: PresetId, defaults: ModelConfigEditable): ModelConfigEditable {
  if (id === 'maximum') return { ...defaults }
  const optionalOff: Partial<ModelConfigEditable> = {
    enable_video_object_detection: false,
    enable_video_shot_detection: false,
    enable_speech_transcription: false,
    keyframes_per_shot: 1,
    adaptive_video_keyframes_enabled: false,
    long_shot_coverage_enabled: false,
    image_captions_enabled: false,
    video_scene_captions_enabled: false,
  }
  return {
    ...defaults,
    ...optionalOff,
    ...(id === 'fast' ? {
      enable_object_detection: false,
      enable_face_recognition: false,
    } : {}),
  }
}

function sameSettings(a: ModelConfigEditable, b: ModelConfigEditable): boolean {
  return Object.keys(a).every(key => a[key as keyof ModelConfigEditable] === b[key as keyof ModelConfigEditable])
}

function Setting({ title, description, children }: {
  title: string
  description: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-200 py-4 last:border-0 dark:border-zinc-700 sm:flex-row sm:items-center sm:justify-between">
      <div className="max-w-xl">
        <div className={labelClass}>{title}</div>
        <p className={helpClass}>{description}</p>
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function Toggle({ label, checked, onChange }: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
      <input
        type="checkbox"
        checked={checked}
        onChange={event => onChange(event.target.checked)}
        className="h-4 w-4 accent-indigo-600"
      />
      {label}
    </label>
  )
}

function Slider({ value, min, max, step, onChange, format = String }: {
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
  format?: (value: number) => string
}) {
  return (
    <div className="flex min-w-48 items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={event => onChange(Number(event.target.value))}
        className="w-36 accent-indigo-500"
      />
      <output className="w-14 text-right text-sm tabular-nums text-zinc-600 dark:text-zinc-300">
        {format(value)}
      </output>
    </div>
  )
}

function NumberInput({ label, value, min, max, onChange, suffix }: {
  label: string
  value: number
  min: number
  max: number
  onChange: (value: number) => void
  suffix?: string
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
      <span className="sr-only">{label}</span>
      <input
        type="number"
        aria-label={label}
        min={min}
        max={max}
        value={value}
        onChange={event => onChange(Number(event.target.value))}
        className={`${inputClass} w-24`}
      />
      {suffix && <span>{suffix}</span>}
    </label>
  )
}

export function ProcessingSettings() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError } = useQuery({ queryKey: ['model-config'], queryFn: getModelConfig })
  const [draft, setDraft] = useState<ModelConfigEditable | null>(null)
  const [savedMessage, setSavedMessage] = useState('')
  const mutation = useMutation({
    mutationFn: patchModelConfig,
    onSuccess: async () => {
      setSavedMessage('Saved. Changes apply to new indexing; reprocess existing media to update it.')
      await queryClient.invalidateQueries({ queryKey: ['model-config'] })
    },
  })

  useEffect(() => {
    if (data) setDraft(data.editable)
  }, [data])

  const presets = useMemo(() => data ? [
    { id: 'maximum' as const, label: 'Maximum detail', values: presetValues('maximum', data.defaults) },
    { id: 'balanced' as const, label: 'Balanced', values: presetValues('balanced', data.defaults) },
    { id: 'fast' as const, label: 'Fast', values: presetValues('fast', data.defaults) },
  ] : [], [data])
  const activePreset = presets.find(preset => draft && sameSettings(preset.values, draft))
  const hasChanges = Boolean(data && draft && !sameSettings(data.editable, draft))

  if (isLoading) return <section className="rounded-lg bg-slate-100 p-4 text-sm text-zinc-500 dark:bg-zinc-800">Loading processing settings…</section>
  if (isError || !data || !draft) return <section role="alert" className="rounded-lg bg-slate-100 p-4 text-sm text-red-500 dark:bg-zinc-800">Could not load processing settings.</section>

  const update = (values: Partial<ModelConfigEditable>) => {
    setDraft(current => current ? { ...current, ...values } : current)
    setSavedMessage('')
  }

  return (
    <section aria-labelledby="processing-settings-title" className="overflow-hidden rounded-lg bg-slate-100 dark:bg-zinc-800">
      <div className="border-b border-slate-200 px-4 py-4 dark:border-zinc-700">
        <h2 id="processing-settings-title" className="text-sm font-semibold text-zinc-800 dark:text-zinc-100">
          Media processing
        </h2>
        <p className={helpClass}>Choose how much detail to extract. These settings stay local to this app.</p>
        <div role="group" aria-label="Processing presets" className="mt-4 flex flex-wrap gap-2">
          {presets.map(preset => (
            <button
              key={preset.id}
              type="button"
              aria-pressed={activePreset?.id === preset.id}
              onClick={() => update(preset.values)}
              className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                activePreset?.id === preset.id
                  ? 'border-indigo-500 bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200'
                  : 'border-slate-300 text-zinc-600 hover:bg-white dark:border-zinc-600 dark:text-zinc-300 dark:hover:bg-zinc-700'
              }`}
            >
              {preset.label}
            </button>
          ))}
          {!activePreset && <span role="status" className="self-center text-xs text-zinc-500">Custom settings</span>}
        </div>
        <p className={helpClass}>
          Maximum detail enables all available analysis. It can take longer, especially on CPU. Balanced keeps core people and object detection; Fast turns those off too.
        </p>
      </div>

      <div className="px-4">
        <div className="py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">People</div>
        <Setting title="Recognize faces" description="Find faces in photos and video keyframes. More processing time is needed when enabled.">
          <Toggle label="On" checked={draft.enable_face_recognition} onChange={value => update({ enable_face_recognition: value })} />
        </Setting>
        {draft.enable_face_recognition && <>
          <Setting title="Face confidence" description="Higher values reduce uncertain matches; the default favors precision.">
            <Slider value={draft.face_confidence_threshold} min={0.5} max={1} step={0.01} format={value => value.toFixed(2)} onChange={value => update({ face_confidence_threshold: value })} />
          </Setting>
          <Setting title="Minimum face size" description="Ignore faces smaller than this many pixels. Lower values can find distant faces but may add false matches.">
            <NumberInput label="Minimum face size" value={draft.face_min_size} min={1} max={500} suffix="pixels" onChange={value => update({ face_min_size: value })} />
          </Setting>
        </>}

        <div className="py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Objects</div>
        <Setting title="Object detection" description="Identify common objects. Automatic skips this on CPU; On extracts more but can be much slower.">
          <select
            aria-label="Object detection"
            value={String(draft.enable_object_detection)}
            onChange={event => {
              const value = event.target.value
              update({ enable_object_detection: value === 'auto' ? 'auto' : value === 'true' })
            }}
            className={inputClass}
          >
            <option value="true">On</option>
            <option value="auto">Automatic (skip on CPU)</option>
            <option value="false">Off</option>
          </select>
        </Setting>
        {draft.enable_object_detection !== false && <Setting title="Object confidence" description="Higher values keep only more certain object detections.">
          <Slider value={draft.object_confidence_threshold} min={0.1} max={0.9} step={0.01} format={value => value.toFixed(2)} onChange={value => update({ object_confidence_threshold: value })} />
        </Setting>}
        <Setting title="Detect objects in videos" description="Analyze selected video frames for objects. Adds processing time and frame-cache use.">
          <Toggle label="On" checked={draft.enable_video_object_detection} onChange={value => update({ enable_video_object_detection: value })} />
        </Setting>

        <div className="py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Video</div>
        <Setting title="Find scene changes" description="Split videos into shots so searches can target individual scenes.">
          <Toggle label="On" checked={draft.enable_video_shot_detection} onChange={value => update({ enable_video_shot_detection: value })} />
        </Setting>
        {draft.enable_video_shot_detection && <>
          <Setting title="Scene-change sensitivity" description="Lower thresholds detect more scene boundaries; higher thresholds merge more footage into longer shots.">
            <Slider value={draft.shot_detection_threshold} min={5} max={60} step={1} format={value => String(Math.round(value))} onChange={value => update({ shot_detection_threshold: value })} />
          </Setting>
          <Setting title="Minimum shot length" description="Shorter shots are kept when this value is low.">
            <NumberInput label="Minimum shot length" value={draft.min_shot_length_frames} min={1} max={300} suffix="frames" onChange={value => update({ min_shot_length_frames: value })} />
          </Setting>
        </>}
        <Setting title="Keyframes per shot" description="More keyframes capture more visual detail from each scene and increase index size.">
          <select
            aria-label="Keyframes per shot"
            value={draft.keyframes_per_shot}
            onChange={event => update({ keyframes_per_shot: Number(event.target.value) })}
            className={inputClass}
          >
            <option value={1}>1 — fewer, faster</option>
            <option value={2}>2 — balanced</option>
            <option value={3}>3 — more detail</option>
          </select>
        </Setting>
        <Setting title="Adaptive keyframes" description="Add frames when a video changes significantly, beyond the regular keyframes.">
          <Toggle label="On" checked={draft.adaptive_video_keyframes_enabled} onChange={value => update({ adaptive_video_keyframes_enabled: value })} />
        </Setting>
        {draft.adaptive_video_keyframes_enabled && <Setting title="Change sensitivity" description="Lower values select more frames; higher values select only larger visual changes.">
          <Slider value={draft.adaptive_keyframe_sensitivity_percent} min={1} max={30} step={1} format={value => `${Math.round(value)}%`} onChange={value => update({ adaptive_keyframe_sensitivity_percent: value })} />
        </Setting>}
        <Setting title="Cover long scenes" description="Add extra frames to long, mostly unchanged scenes so important details are not missed.">
          <Toggle label="On" checked={draft.long_shot_coverage_enabled} onChange={value => update({ long_shot_coverage_enabled: value })} />
        </Setting>
        {draft.long_shot_coverage_enabled && <>
          <Setting title="Long-scene threshold" description="Scenes longer than this receive extra coverage frames.">
            <NumberInput label="Long-scene threshold" value={draft.long_shot_min_duration_seconds} min={1} max={3600} suffix="seconds" onChange={value => update({ long_shot_min_duration_seconds: value })} />
          </Setting>
          <Setting title="Extra frame interval" description="Smaller intervals capture more detail in long scenes.">
            <NumberInput label="Extra frame interval" value={draft.long_shot_interval_seconds} min={1} max={3600} suffix="seconds" onChange={value => update({ long_shot_interval_seconds: value })} />
          </Setting>
        </>}

        <div className="py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Captions & speech</div>
        <Setting title="Transcribe speech" description="Create searchable transcripts for speech in videos. The local transcription files are downloaded when needed.">
          <Toggle label="On" checked={draft.enable_speech_transcription} onChange={value => update({ enable_speech_transcription: value })} />
        </Setting>
        <Setting title="Describe photos" description="Generate searchable text descriptions for photos. This adds setup and indexing time.">
          <Toggle label="On" checked={draft.image_captions_enabled} onChange={value => update({ image_captions_enabled: value })} />
        </Setting>
        <Setting title="Describe video scenes" description="Generate searchable descriptions for video scenes and keyframes.">
          <Toggle label="On" checked={draft.video_scene_captions_enabled} onChange={value => update({ video_scene_captions_enabled: value })} />
        </Setting>

        <div className="py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">Performance & storage</div>
        <Setting title="Video frame cache" description="Disk space reserved for extracted video frames. Increase this if you process long or many videos.">
          <NumberInput label="Video frame cache budget" value={draft.video_frame_cache_budget_mb} min={128} max={16384} suffix="MB" onChange={value => update({ video_frame_cache_budget_mb: value })} />
        </Setting>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-4 dark:border-zinc-700">
        <div className="min-h-5 text-xs" aria-live="polite">
          {mutation.isError && <span className="text-red-500">Could not save. Your edits are still here; try again.</span>}
          {!mutation.isError && savedMessage && <span className="text-emerald-600 dark:text-emerald-400">{savedMessage}</span>}
          {!mutation.isError && !savedMessage && hasChanges && <span className="text-amber-600 dark:text-amber-400">Unsaved changes</span>}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => { setDraft(presetValues('maximum', data.defaults)); setSavedMessage('') }}
            disabled={mutation.isPending || sameSettings(draft, data.defaults)}
            className="rounded-md border border-slate-300 px-3 py-2 text-sm text-zinc-600 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-600 dark:text-zinc-300 dark:hover:bg-zinc-700"
          >
            Reset to Maximum detail
          </button>
          <button
            type="button"
            onClick={() => mutation.mutate(draft)}
            disabled={!hasChanges || mutation.isPending}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {mutation.isPending ? 'Saving…' : 'Save settings'}
          </button>
        </div>
      </div>
    </section>
  )
}
