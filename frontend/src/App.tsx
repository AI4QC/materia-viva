import { useEffect, useState } from 'react'
import { Atom, Github, Languages, Moon, Sun } from 'lucide-react'

import { MaterialDetail } from './components/MaterialDetail'
import { SearchWorkspace } from './components/SearchWorkspace'
import { useI18n } from './i18n'
import { parseQuery, serializeQuery, type MaterialQuery } from './lib/query'

type Theme = 'dark' | 'light'

const THEME_STORAGE_KEY = 'mv-theme'

function initialTheme(): Theme {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
  if (stored === 'dark' || stored === 'light') return stored
  if (typeof window.matchMedia === 'function') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return 'dark'
}

export default function App() {
  const [query, setQuery] = useState<MaterialQuery>(() => parseQuery(new URLSearchParams(window.location.search)))
  const [selectedMaterial, setSelectedMaterial] = useState<string | null>(null)
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const { lang, setLang, t } = useI18n()

  useEffect(() => {
    const params = serializeQuery(query).toString()
    window.history.replaceState(null, '', params ? `?${params}` : window.location.pathname)
  }, [query])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.style.colorScheme = theme
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label={t('brand.home')}>
          <span className="brand__mark"><Atom size={21} /></span>
          <span><b>MateriaViva</b><small>{t('brand.tagline')}</small></span>
        </a>
        <nav aria-label={t('nav.main')}>
          <a href="#element-lab-title">{t('nav.elements')}</a>
          <a href="#catalog-title">{t('nav.catalog')}</a>
          <button
            aria-label={t('lang.switchTo')}
            className="lang-toggle"
            onClick={() => setLang(lang === 'en' ? 'zh' : 'en')}
            type="button"
          >
            <span className="lang-toggle__icon" aria-hidden="true"><Languages size={14} /></span>
            <span>{t('lang.short')}</span>
          </button>
          <button
            aria-label={theme === 'dark' ? t('theme.toLight') : t('theme.toDark')}
            aria-pressed={theme === 'light'}
            className="theme-toggle"
            data-theme-target={theme === 'dark' ? 'light' : 'dark'}
            onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
            type="button"
          >
            <span className="theme-toggle__icon" aria-hidden="true">
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </span>
            <span>{theme === 'dark' ? t('theme.light') : t('theme.dark')}</span>
          </button>
          <span className="system-status"><i /> {t('nav.status')}</span>
        </nav>
      </header>

      <SearchWorkspace query={query} onQueryChange={setQuery} onSelectMaterial={setSelectedMaterial} />

      {selectedMaterial && <MaterialDetail materialId={selectedMaterial} onClose={() => setSelectedMaterial(null)} />}

      <footer className="site-footer">
        <div><Atom size={17} /><span>MateriaViva</span></div>
        <p>{t('footer.tagline')}</p>
        <a href="https://github.com/AI4QC/materia-viva" aria-label="GitHub"><Github size={17} /></a>
      </footer>
    </div>
  )
}
