import { defineConfig, loadEnv, type ProxyOptions } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

function toWsOrigin(httpOrigin: string): string {
  const url = new URL(httpOrigin)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString().replace(/\/$/, '')
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiOrigin = (env.VITE_API_ORIGIN || 'http://localhost:8000').replace(/\/$/, '')
  const wsOrigin = (env.VITE_WS_ORIGIN || toWsOrigin(apiOrigin)).replace(/\/$/, '')
  const devPort = Number(env.VITE_DEV_PORT || 5173)
  const apiProxy = (): ProxyOptions => ({
    target: apiOrigin,
    bypass: (req) => req.headers.accept?.includes('text/html') ? req.url : undefined,
  })

  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
    },
    server: {
      port: devPort,
      proxy: {
        '/health':          apiProxy(),
        '/api':             apiProxy(),
        '/search':          apiProxy(),
        '/transcripts':     apiProxy(),
        '/track':           apiProxy(),
        '/media':           apiProxy(),
        '/images':          apiProxy(),
        '/videos':          apiProxy(),
        '/video-keyframes': apiProxy(),
        '/faces':           apiProxy(),
        '/people':          apiProxy(),
        '/tags':            apiProxy(),
        '/user-tags':       apiProxy(),
        '/collections':     apiProxy(),
        '/indexer':         apiProxy(),
        '/config':          apiProxy(),
        '/platform':        apiProxy(),
        '/browse':          apiProxy(),
        '/diagnostics':     apiProxy(),
        '/logs':            apiProxy(),
        '/thumbnails':      apiProxy(),
        '/face_thumbnails': apiProxy(),
        '/ws': { target: wsOrigin, ws: true },
      },
    },
  }
})
