import { useEffect, useState } from 'react'
import { Check, Clock3, Download } from 'lucide-react'
import { ProgressBar, SplashShell } from './splash'

type View = 'prompt' | 'progress' | 'done' | 'later'

const PREVIEW_DURATION_MS = 16_000
const ESTIMATED_SETUP_MINUTES = 8

export function SetupPrototype() {
  const [view, setView] = useState<View>('prompt')
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    if (view !== 'progress') return

    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      const next = Math.min(100, ((Date.now() - startedAt) / PREVIEW_DURATION_MS) * 100)
      setProgress(next)
      if (next === 100) {
        window.clearInterval(timer)
        setView('done')
      }
    }, 250)

    return () => window.clearInterval(timer)
  }, [view])

  const continueToApp = () => {
    const url = new URL(window.location.href)
    url.searchParams.delete('setup-prototype')
    window.location.assign(`${url.pathname}${url.search}${url.hash}`)
  }

  if (view === 'progress') {
    const remainingMinutes = Math.max(1, Math.ceil(ESTIMATED_SETUP_MINUTES * (1 - progress / 100)))
    return (
      <SplashShell icon={<Download size={22} className="shrink-0 text-sky-400" aria-hidden />}>
        <p className="text-base font-medium text-slate-100">Setting up Media Search Agent</p>
        <p className="mt-1 text-sm text-slate-400">About {remainingMinutes} minutes remaining</p>
        <ProgressBar pct={progress} rightLabel="Please keep the app open" />
        <p className="mt-5 text-xs text-slate-500">
          Setup only happens once. You can start using the app when it finishes.
        </p>
      </SplashShell>
    )
  }

  if (view === 'done') {
    return (
      <SplashShell icon={<Check size={22} className="shrink-0 text-emerald-400" aria-hidden />}>
        <p className="text-base font-medium text-slate-100">Setup complete</p>
        <p className="mt-1 text-sm text-slate-400">Media Search Agent is ready to use.</p>
        <button
          type="button"
          onClick={continueToApp}
          className="mt-6 w-full rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-sky-400"
        >
          Continue
        </button>
      </SplashShell>
    )
  }

  if (view === 'later') {
    return (
      <SplashShell icon={<Clock3 size={22} className="shrink-0 text-slate-400" aria-hidden />}>
        <p className="text-base font-medium text-slate-100">Setup postponed</p>
        <p className="mt-1 text-sm text-slate-400">You can return and finish setup when you are ready.</p>
        <button
          type="button"
          onClick={() => setView('prompt')}
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
          <p className="text-sm text-slate-200">Usually takes about 5–15 minutes</p>
          <p className="mt-0.5 text-xs text-slate-500">Please keep the app open until setup finishes.</p>
        </div>
      </div>
      <button
        type="button"
        onClick={() => setView('progress')}
        className="mt-6 w-full rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-sky-400"
      >
        Set up now
      </button>
      <button
        type="button"
        onClick={() => setView('later')}
        className="mt-2 w-full rounded-xl px-4 py-2.5 text-sm text-slate-400 hover:bg-slate-800 hover:text-slate-200"
      >
        Set up later
      </button>
      <p className="mt-4 text-center text-[11px] text-slate-600">
        Prototype preview: progress is accelerated.
      </p>
    </SplashShell>
  )
}
