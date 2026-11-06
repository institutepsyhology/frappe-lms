// Experiment only. Compare artifacts and exercise the browser before release.
// Splitting known large dependency families avoids rendering one giant chunk.
import { mergeConfig } from 'vite'
import original from './vite.config.js'

export default async (environment) => mergeConfig(
  typeof original === 'function' ? await original(environment) : original,
  {
    build: {
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('/node_modules/@tensorflow/')) return 'tensorflow'
            if (id.includes('/node_modules/face-api.js/')) return 'face-api'
            if (id.includes('/node_modules/pdfjs-dist/')) return 'pdfjs'
            if (id.includes('/node_modules/highlight.js/')) return 'highlight'
          },
        },
      },
    },
  },
)
