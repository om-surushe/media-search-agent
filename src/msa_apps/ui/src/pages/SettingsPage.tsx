import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Check, ExternalLink } from 'lucide-react'
import { getDiagnostics, getPlatform, type Diagnostics } from '../api/indexer'
import { ProcessingSettings } from '../components/ProcessingSettings'

// Log names that have a corresponding GET /logs/{name} endpoint
const LOG_KEYS = new Set(['app', 'uvicorn', 'qdrant', 'launch', 'install', 'stop'])

function PathRow({ label, value, logKey }: { label: string; value: string; logKey?: string }) {
  const [copied, setCopied] = useState(false)
  function copy() {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <li className="flex items-center gap-3 px-4 py-2.5">
      <span className="text-xs text-zinc-400 dark:text-zinc-500 w-24 shrink-0">{label}</span>
      <span className="text-xs font-mono text-zinc-500 dark:text-zinc-400 truncate flex-1">
        {value}
      </span>
      <div className="flex items-center gap-2 shrink-0">
        {logKey && (
          <a
            href={`/logs/${logKey}`}
            target="_blank"
            rel="noreferrer"
            title="Open log in browser"
            className="text-zinc-300 dark:text-zinc-600 hover:text-indigo-500 dark:hover:text-indigo-400 transition-colors"
          >
            <ExternalLink size={12} />
          </a>
        )}
        <button
          onClick={copy}
          title="Copy path"
          className="text-zinc-300 dark:text-zinc-600 hover:text-zinc-500 dark:hover:text-zinc-400 transition-colors"
        >
          {copied ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
        </button>
      </div>
    </li>
  )
}

/**
 * Optional `msa` command-line tool tier. The desktop install provisions the venv but
 * doesn't put `msa` on PATH; this discloses the tool and shows the opt-in command
 * (docs-command approach — no PATH mutation from the sandboxed webview).
 */
function CliToolSection({ cli }: { cli: NonNullable<Diagnostics['cli']> }) {
  const { data } = useQuery({ queryKey: ['platform'], queryFn: getPlatform })
  const platform = data?.platform
  const installed = cli.launcher_installed || cli.on_path

  // Nothing to offer if the backend can't locate its own msa console script.
  if (!cli.msa_path) return null

  const posix = platform === 'macos' || platform === 'linux' || platform === 'wsl2'

  return (
    <div className="bg-slate-100 dark:bg-zinc-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-zinc-700 text-sm font-medium text-zinc-700 dark:text-zinc-200">
        Command-line tool
      </div>
      <div className="px-4 py-3 space-y-2 text-xs text-zinc-600 dark:text-zinc-300">
        {installed ? (
          <p>
            The <code>msa</code> command-line tool is available in your terminal. Power users
            can run <code>msa index run</code> for headless indexing.
          </p>
        ) : posix ? (
          <>
            <p>
              Install the optional <code>msa</code> command-line tool (for headless indexing,
              e.g. <code>msa index run</code>). In Terminal, run:
            </p>
            <code className="block px-2 py-1 rounded bg-slate-200 dark:bg-zinc-900 font-mono break-all select-all">
              {`if [ -e ~/.local/bin/msa ] || [ -L ~/.local/bin/msa ]; then echo "~/.local/bin/msa already exists — remove it first"; else mkdir -p ~/.local/bin && ln -s "${cli.msa_path}" ~/.local/bin/msa; fi`}
            </code>
            <p className="text-zinc-500 dark:text-zinc-400">
              Ensure <code>~/.local/bin</code> is on your PATH. The command won’t overwrite an
              existing <code>msa</code>; uninstalling the app removes the link it creates.
            </p>
          </>
        ) : (
          <>
            <p>
              The optional <code>msa</code> command-line tool lives at:
            </p>
            <code className="block px-2 py-1 rounded bg-slate-200 dark:bg-zinc-900 font-mono break-all select-all">
              {cli.msa_path}
            </code>
            <p className="text-zinc-500 dark:text-zinc-400">
              Add its folder to your PATH to run it as <code>msa</code>, or call it directly.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────

// Served as a release asset (release.yml stages scripts/uninstall-desktop.sh) so the
// one-liner always matches the released app.
const UNINSTALL_ONE_LINER =
  'curl -fsSL https://github.com/openara-ai/media-search-agent/releases/latest/download/uninstall-desktop.sh | bash'

/** Platform-aware uninstall instructions (ADR-005 tiers; parity with the old tray menu). */
function UninstallSection() {
  const { data } = useQuery({ queryKey: ['platform'], queryFn: getPlatform })
  const [open, setOpen] = useState(false)
  const platform = data?.platform

  return (
    <div className="bg-slate-100 dark:bg-zinc-800 rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-zinc-700 text-sm font-medium text-zinc-700 dark:text-zinc-200">
        Uninstall
      </div>
      <div className="px-4 py-3 space-y-3">
        <button
          onClick={() => setOpen(o => !o)}
          className="text-xs text-red-600 dark:text-red-400 hover:underline"
        >
          Uninstall Media Search Agent…
        </button>
        {open && (
          <div className="text-xs text-zinc-600 dark:text-zinc-300 space-y-2">
            {platform === 'windows' && (
              <ol className="list-decimal ml-4 space-y-1">
                <li>Quit Media Search Agent.</li>
                <li>Open Windows Settings → Apps → Installed apps → Media Search Agent → Uninstall.</li>
                <li>
                  Your app data are kept by default — they are only removed
                  if you tick “Delete the application data” in the uninstaller.
                </li>
              </ol>
            )}
            {platform === 'macos' && (
              <ol className="list-decimal ml-4 space-y-1">
                <li>Quit Media Search Agent.</li>
                <li>
                  In Terminal, run:
                  <code className="block mt-1 px-2 py-1 rounded bg-slate-200 dark:bg-zinc-900 font-mono break-all select-all">
                    {UNINSTALL_ONE_LINER}
                  </code>
                </li>
                <li>Your app data are kept by default.</li>
              </ol>
            )}
            {(platform === 'linux' || platform === 'wsl2') && (
              <p>
                This install uses the shell bundle: run <code>msa uninstall</code> (or{' '}
                <code>scripts/uninstall.sh</code> from the install directory). Your index and
                config are kept unless you confirm their deletion at the prompt.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────

export function SettingsPage() {
  const { data: diag } = useQuery({ queryKey: ['diagnostics'], queryFn: getDiagnostics })

  // Source the version from the backend (_APP_VERSION → importlib.metadata, stamped from
  // the git tag at release build). We deliberately do NOT use window.__APP_VERSION__: the
  // shell injects env!("CARGO_PKG_VERSION"), but src-tauri/Cargo.toml is never stamped at
  // release (only tauri.conf.json is), so it would report a stale "0.1.0" in every package.
  const appVersion = diag?.app_version

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Settings</h1>

      <ProcessingSettings />

      {/* Diagnostics */}
      {diag && (
        <div className="bg-slate-100 dark:bg-zinc-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-zinc-700 text-sm font-medium text-zinc-700 dark:text-zinc-200">
            Diagnostics
          </div>
          <ul className="divide-y divide-slate-200 dark:divide-zinc-700">
            <PathRow label="Config"   value={diag.config_file} />
            <PathRow label="SQLite"   value={diag.sqlite_path} />
            {Object.entries(diag.logs).map(([key, filePath]) => (
              <PathRow
                key={key}
                label={key.charAt(0).toUpperCase() + key.slice(1) + ' log'}
                value={filePath}
                logKey={LOG_KEYS.has(key) ? key : undefined}
              />
            ))}
            <PathRow label="Backend" value={diag.api_url} />
            {diag.qdrant_url && <PathRow label="Qdrant" value={diag.qdrant_url} />}
          </ul>
        </div>
      )}

      {/* About */}
      <div className="bg-slate-100 dark:bg-zinc-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200 dark:border-zinc-700 text-sm font-medium text-zinc-700 dark:text-zinc-200">
          About
        </div>
        <ul className="divide-y divide-slate-200 dark:divide-zinc-700">
          <li className="flex items-center gap-3 px-4 py-2.5">
            <span className="text-xs text-zinc-400 dark:text-zinc-500 w-24 shrink-0">Version</span>
            <span className="text-xs font-mono text-zinc-500 dark:text-zinc-400 flex-1">
              {appVersion ?? 'unknown'}
            </span>
          </li>
        </ul>
      </div>

      {/* Command-line tool (optional msa CLI opt-in) */}
      {diag?.cli && <CliToolSection cli={diag.cli} />}

      {/* Uninstall */}
      <UninstallSection />
    </div>
  )
}
