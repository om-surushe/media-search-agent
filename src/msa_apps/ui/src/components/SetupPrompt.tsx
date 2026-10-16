import { useState } from 'react'
import { Clock3, Download } from 'lucide-react'
import { SplashShell } from './splash'

export function SetupPrompt({ onStart }: { onStart: () => Promise<void> }) {
  const [later, setLater] = useState(false)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const startSetup = async () => {
    setStarting(true)
    setError(null)
    try {
      await onStart()
    } catch {
      setError('Setup could not start. Please try again.')
      setStarting(false)
    }
  }

  if (later) {
    return (
      <SplashShell icon={<Clock3 size={22} className="shrink-0 text-slate-400" aria-hidden />}>
        <p className="text-base font-medium text-slate-100">Setup postponed</p>
        <p className="mt-1 text-sm text-slate-400">You can return and finish setup when you are ready.</p>
        <button
          type="button"
          onClick={() => setLater(false)}
          className="mt-6 w-full rounded-xl border border-slate-700 px-4 py-2.5 text-sm font-medium text-slate-200 hover:bg-slate-800"
        >
          Back
        </button>
      </SplashShell>
    )
  }

  return (
    <SplashShell icon={<Download size={22} className="shrink-0 text-sky-400" aria-hidden />}>
      <p className="text-base font-medium text-slate-100">Finish setting up</p>
      <p className="mt-2 text-sm text-slate-400">
        Media Search Agent needs a one-time setup before you can search your library.
      </p>
      <div className="mt-4 flex items-start gap-3 rounded-xl border border-slate-800 bg-slate-950/50 p-3">
        <Clock3 size={17} className="mt-0.5 shrink-0 text-sky-400" aria-hidden />
        <div>
          <p className="text-sm text-slate-200">The time estimate appears after setup begins</p>
          <p className="mt-0.5 text-xs text-slate-500">You may close the app; setup resumes next time.</p>
        </div>
      </div>
      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}
      <button
        type="button"
        onClick={() => void startSetup()}
        disabled={starting}
        className="mt-6 w-full rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-sky-400 disabled:cursor-wait disabled:opacity-60"
      >
        {starting ? 'Starting setup…' : 'Set up now'}
      </button>
      <button
        type="button"
        onClick={() => setLater(true)}
        className="mt-2 w-full rounded-xl px-4 py-2.5 text-sm text-slate-400 hover:bg-slate-800 hover:text-slate-200"
      >
        Set up later
      </button>
    </SplashShell>
  )
}
