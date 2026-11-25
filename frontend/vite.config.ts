import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { execSync } from 'node:child_process'

// Version shown in the dashboard: the release tag the build was made from (see the
// "Versions and releases" section of the README). Read at build time, so it never needs
// bumping by hand.
function appVersion(): string {
  try {
    return execSync('git describe --tags --always --dirty', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().trim() || 'dev'
  } catch {
    return 'dev'
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion()),
  },
  build: {
    rollupOptions: {
      output: {
        // Split rarely-changing vendors into their own cacheable chunks so the app
        // chunk stays small and chart.js/react don't reload on every app change (B10).
        manualChunks: {
          'react-vendor': ['react', 'react-dom'],
          charts: ['chart.js'],
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://ikabot-gui:5000',
        changeOrigin: true,
      },
    },
  },
})
