import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { USE_MOCK } from './api.js'

// Without VITE_API_BASE the app runs on web/mock/ (MSW in a service worker),
// which answers exactly like docs/api_contract.md. With it, the real API.
async function start() {
  if (USE_MOCK) {
    const { worker } = await import('../mock/browser.js')
    await worker.start({ onUnhandledRequest: 'bypass', quiet: true })
  }
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

start()
