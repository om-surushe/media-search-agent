import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SettingsPage } from './SettingsPage'

// ── API mock ───────────────────────────────────────────────────────────────

const modelConfigData = {
  editable: {
    enable_object_detection: true,
    object_confidence_threshold: 0.35,
    enable_video_object_detection: true,
    enable_face_recognition: true,
    face_confidence_threshold: 0.95,
    face_min_size: 60,
    enable_video_shot_detection: true,
    enable_speech_transcription: true,
    shot_detection_threshold: 30,
    min_shot_length_frames: 15,
    keyframes_per_shot: 3,
    adaptive_video_keyframes_enabled: true,
    adaptive_keyframe_sensitivity_percent: 8,
    long_shot_coverage_enabled: true,
    long_shot_min_duration_seconds: 30,
    long_shot_interval_seconds: 10,
    video_frame_cache_budget_mb: 1024,
    image_captions_enabled: true,
    video_scene_captions_enabled: true,
  },
  defaults: {
    enable_object_detection: true,
    object_confidence_threshold: 0.35,
    enable_video_object_detection: true,
    enable_face_recognition: true,
    face_confidence_threshold: 0.95,
    face_min_size: 60,
    enable_video_shot_detection: true,
    enable_speech_transcription: true,
    shot_detection_threshold: 30,
    min_shot_length_frames: 15,
    keyframes_per_shot: 3,
    adaptive_video_keyframes_enabled: true,
    adaptive_keyframe_sensitivity_percent: 8,
    long_shot_coverage_enabled: true,
    long_shot_min_duration_seconds: 30,
    long_shot_interval_seconds: 10,
    video_frame_cache_budget_mb: 1024,
    image_captions_enabled: true,
    video_scene_captions_enabled: true,
  },
  effective: { object_detection_enabled: true },
}

const diagData = {
  msa_root: '/home/user/msa',
  config_file: '/home/user/msa/config.yaml',
  sqlite_path: '/home/user/msa/index/media.sqlite',
  log_dir: '/home/user/msa/logs',
  logs: {
    app:     '/home/user/msa/logs/msa.log',
    uvicorn: '/home/user/msa/logs/uvicorn.log',
    qdrant:  '/home/user/msa/logs/qdrant.log',
    desktop: '/home/user/msa/logs/msa-desktop.log',
    launch:  '/home/user/msa/logs/launch-2026-03-24_170000.log',
  },
  qdrant_url: 'http://localhost:6333',
  api_url: 'http://localhost:52341',
  app_version: '0.3.2',
  cli: {
    msa_path: '/home/user/msa/.venv/bin/msa',
    launcher_path: '/home/user/.local/bin/msa',
    launcher_installed: false,
    on_path: false,
  },
}

function mockFetch(platform = 'macos', diag: Record<string, unknown> = diagData): void {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url === '/diagnostics')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(diag) })
    if (url === '/platform')
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ platform }) })
    if (url === '/config/model')
      return Promise.resolve({ ok: true, json: () => Promise.resolve(modelConfigData) })
    // DELETE / POST
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'ok' }) })
  }))
}

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } })
}

function renderPage() {
  return render(
    <QueryClientProvider client={makeClient()}>
      <SettingsPage />
    </QueryClientProvider>
  )
}

beforeEach(() => mockFetch())
afterEach(() => vi.unstubAllGlobals())

// ── Tests ──────────────────────────────────────────────────────────────────

describe('SettingsPage', () => {
  describe('diagnostics', () => {
    it('renders diagnostics section heading', async () => {
      renderPage()
      await waitFor(() => expect(screen.getByText('Diagnostics')).toBeInTheDocument())
    })

    it('log entries have an external link (open in browser)', async () => {
      renderPage()
      await waitFor(() => screen.getByText('Diagnostics'))
      // Log entries render an <a> with the /logs/{key} href
      const links = screen.getAllByTitle('Open log in browser')
      expect(links.length).toBeGreaterThanOrEqual(3) // app, uvicorn, qdrant, launch
      links.forEach(link => {
        expect(link).toHaveAttribute('href', expect.stringMatching(/^\/logs\//))
      })
    })

    it('Config and SQLite entries have no external link', async () => {
      renderPage()
      await waitFor(() => screen.getByText('Diagnostics'))
      const links = screen.getAllByTitle('Open log in browser')
      const hrefs = links.map(l => l.getAttribute('href') ?? '')
      // /logs/app etc. — none should be /config or /sqlite
      expect(hrefs.every(h => h.startsWith('/logs/'))).toBe(true)
    })

    it('shows the backend url (port) row', async () => {
      renderPage()
      await waitFor(() => screen.getByText('Diagnostics'))
      expect(screen.getByText('Backend')).toBeInTheDocument()
      expect(screen.getByText('http://localhost:52341')).toBeInTheDocument()
    })

    it('shows the desktop log location without an external link', async () => {
      renderPage()
      await waitFor(() => screen.getByText('Diagnostics'))
      expect(screen.getByText('Desktop log')).toBeInTheDocument()
      expect(screen.getByText('/home/user/msa/logs/msa-desktop.log')).toBeInTheDocument()
      // msa-desktop.log has no GET /logs/{name} viewer, so no open-in-browser link
      const links = screen.getAllByTitle('Open log in browser')
      expect(links.some(l => (l.getAttribute('href') ?? '').includes('desktop'))).toBe(false)
    })
  })

  describe('about', () => {
    it('renders About heading and the backend-reported version', async () => {
      renderPage()
      // About/Version render immediately; the version resolves once diagnostics loads.
      expect(screen.getByText('About')).toBeInTheDocument()
      expect(screen.getByText('Version')).toBeInTheDocument()
      await waitFor(() => expect(screen.getByText('0.3.2')).toBeInTheDocument())
    })

    it('uses the backend version, NOT the shell-injected window.__APP_VERSION__', async () => {
      // Regression guard: window.__APP_VERSION__ is env!("CARGO_PKG_VERSION") from the never-
      // stamped src-tauri/Cargo.toml (stale "0.1.0"), so the backend app_version must win.
      // jsdom's window is the global object, so stubbing the global injects window.__APP_VERSION__.
      // afterEach → vi.unstubAllGlobals() restores it (and the fetch mock) for the next test.
      vi.stubGlobal('__APP_VERSION__', '0.1.0')
      renderPage()
      await waitFor(() => expect(screen.getByText('0.3.2')).toBeInTheDocument())
      expect(screen.queryByText('0.1.0')).toBeNull()
    })
  })

  describe('command-line tool (msa CLI opt-in)', () => {
    it('macOS not-installed: shows a non-clobbering symlink opt-in targeting the venv msa', async () => {
      renderPage()
      await waitFor(() => expect(screen.getByText('Command-line tool')).toBeInTheDocument())
      // Non-clobbering: `ln -s` (no -f) guarded by an existence check, targeting our venv msa.
      expect(
        screen.getByText(/ln -s "\/home\/user\/msa\/\.venv\/bin\/msa" ~\/\.local\/bin\/msa/),
      ).toBeInTheDocument()
      expect(screen.getByText(/already exists — remove it first/)).toBeInTheDocument()
      // Must NOT force-overwrite an existing launcher.
      expect(screen.queryByText(/ln -sf/)).toBeNull()
    })

    it('Windows not-installed: shows the executable path, no symlink command', async () => {
      mockFetch('windows', {
        ...diagData,
        cli: { msa_path: 'C:\\Users\\u\\msa\\.venv\\Scripts\\msa.exe', launcher_path: null, launcher_installed: false, on_path: false },
      })
      renderPage()
      await waitFor(() => expect(screen.getByText('Command-line tool')).toBeInTheDocument())
      expect(screen.getByText(/Scripts\\msa\.exe/)).toBeInTheDocument()
      expect(screen.queryByText(/ln -s /)).toBeNull()
    })

    it('already installed: states the tool is available, no install command', async () => {
      mockFetch('macos', {
        ...diagData,
        cli: { msa_path: '/home/user/msa/.venv/bin/msa', launcher_path: '/home/user/.local/bin/msa', launcher_installed: true, on_path: false },
      })
      renderPage()
      await waitFor(() =>
        expect(screen.getByText(/is available in your terminal/)).toBeInTheDocument(),
      )
      expect(screen.queryByText(/ln -s /)).toBeNull()
    })

    it('no msa_path: section is omitted entirely', async () => {
      mockFetch('macos', {
        ...diagData,
        cli: { msa_path: null, launcher_path: null, launcher_installed: false, on_path: false },
      })
      renderPage()
      await waitFor(() => expect(screen.getByText('Diagnostics')).toBeInTheDocument())
      expect(screen.queryByText('Command-line tool')).toBeNull()
    })
  })

  describe('uninstall', () => {
    it('renders the Uninstall section with instructions collapsed', () => {
      renderPage()
      expect(screen.getByText('Uninstall')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /Uninstall Media Search Agent/ })).toBeInTheDocument()
      expect(screen.queryByText(/kept by default/)).toBeNull()
    })

    it('macOS instructions show the uninstall-desktop.sh one-liner and default-keep wording', async () => {
      renderPage()
      await userEvent.click(screen.getByRole('button', { name: /Uninstall Media Search Agent/ }))
      await waitFor(() =>
        expect(screen.getByText(/uninstall-desktop\.sh/)).toBeInTheDocument()
      )
      // ADR-005 Tier-2 posture must be stated: user data is kept by default.
      expect(screen.getByText(/app data are kept by default/)).toBeInTheDocument()
    })

    it('Windows instructions point at Apps and the app-data checkbox (default keep)', async () => {
      mockFetch('windows')
      renderPage()
      await userEvent.click(screen.getByRole('button', { name: /Uninstall Media Search Agent/ }))
      await waitFor(() => expect(screen.getByText(/Installed apps/)).toBeInTheDocument())
      expect(screen.getByText(/Delete the application data/)).toBeInTheDocument()
      expect(screen.getByText(/kept by default/)).toBeInTheDocument()
    })

    it('Linux/WSL2 points at the shell-bundle uninstall path', async () => {
      mockFetch('linux')
      renderPage()
      await userEvent.click(screen.getByRole('button', { name: /Uninstall Media Search Agent/ }))
      await waitFor(() => expect(screen.getByText(/msa uninstall/)).toBeInTheDocument())
    })
  })

  it('shows descriptive extraction settings without model names or catalogs', async () => {
    renderPage()
    expect(await screen.findByText('Media processing')).toBeInTheDocument()
    expect(screen.getByText('Maximum detail')).toBeInTheDocument()
    expect(screen.getByText('Scene-change sensitivity')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '2 — balanced' })).toBeInTheDocument()
    expect(screen.getByText('Describe photos')).toBeInTheDocument()
    expect(screen.getByText('Config')).toBeInTheDocument()
    expect(screen.queryByText(/Model Configuration|CLIP|Model catalog|Model cache|ViT-L-14/)).toBeNull()
    expect(screen.queryByText('Models')).toBeNull()
  })

  it('keeps edits as drafts until Save is clicked', async () => {
    renderPage()
    await screen.findByText('Media processing')
    const toggle = screen.getAllByRole('checkbox')[0]
    await userEvent.click(toggle)
    expect(fetch).not.toHaveBeenCalledWith('/config/model', expect.objectContaining({ method: 'PATCH' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save settings' }))
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      '/config/model',
      expect.objectContaining({ method: 'PATCH' }),
    ))
  })

  it('changes presets and Reset in draft without saving', async () => {
    renderPage()
    await screen.findByText('Media processing')
    const balanced = screen.getByRole('button', { name: 'Balanced' })
    await userEvent.click(balanced)
    expect(balanced).toHaveAttribute('aria-pressed', 'true')
    expect(fetch).not.toHaveBeenCalledWith('/config/model', expect.objectContaining({ method: 'PATCH' }))

    await userEvent.click(screen.getByRole('button', { name: 'Reset to Maximum detail' }))
    expect(screen.getByRole('button', { name: 'Maximum detail' })).toHaveAttribute('aria-pressed', 'true')
    expect(fetch).not.toHaveBeenCalledWith('/config/model', expect.objectContaining({ method: 'PATCH' }))
  })
})
