import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { defaultThemeId } from './app/theme/theme-registry'
import { loadStoredThemeId } from './app/theme/theme-storage'
import { AppErrorBoundary } from './app/AppErrorBoundary'
import './index.css'
import App from './App.tsx'
import { forgetTokenFromBeforeWebUIServer } from './api/http'

document.documentElement.dataset.theme = loadStoredThemeId(defaultThemeId)
forgetTokenFromBeforeWebUIServer()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
)
