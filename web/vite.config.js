import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}', 'mock/**/*.test.js'],
    // jsdom has no layout: the app code reads `window.location.origin` as the
    // API base, and the mock answers any origin.
    environmentOptions: { jsdom: { url: 'http://localhost:5173' } },
  },
})
