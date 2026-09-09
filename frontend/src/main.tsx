import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import '@fontsource-variable/ibm-plex-sans'
import '@fontsource-variable/noto-sans-sc'
import '@fontsource-variable/space-grotesk'

import App from './App'
import { I18nProvider } from './i18n'
import './styles/tokens.css'
import './styles/global.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode><I18nProvider><App /></I18nProvider></StrictMode>,
)
