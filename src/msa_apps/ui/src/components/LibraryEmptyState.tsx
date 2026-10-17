import { Link } from 'react-router-dom'

export function LibraryEmptyState({ indexing }: { indexing: boolean }) {
  return (
    <section className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 dark:border-zinc-700 px-6 py-10 text-center">
      <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
        {indexing ? 'Your media is being indexed' : 'Your library is not indexed yet'}
      </h2>
      <p className="max-w-md text-xs text-zinc-500 dark:text-zinc-400">
        {indexing
          ? 'Photos and videos will appear here when indexing finishes.'
          : 'Add a folder containing photos or videos, then index it to search and explore your media.'}
      </p>
      <Link to="/indexer" className="mt-1 rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500">
        {indexing ? 'View indexing progress' : 'Add a media folder'}
      </Link>
    </section>
  )
}
