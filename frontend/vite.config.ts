import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
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
