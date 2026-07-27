import { useEffect, useState } from 'react'
import { Atom, Github, Moon, Sun } from 'lucide-react'

import { MaterialDetail } from './components/MaterialDetail'
import { SearchWorkspace } from './components/SearchWorkspace'
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
        <a className="brand" href="/" aria-label="MateriaViva 首页">
          <span className="brand__mark"><Atom size={21} /></span>
          <span><b>MateriaViva</b><small>自进化材料数据库</small></span>
        </a>
        <nav aria-label="主导航">
          <a href="#element-lab-title">元素检索</a>
          <a href="#catalog-title">结构目录</a>
          <button
            aria-label={theme === 'dark' ? '切换到日间模式' : '切换到夜间模式'}
            aria-pressed={theme === 'light'}
            className="theme-toggle"
            data-theme-target={theme === 'dark' ? 'light' : 'dark'}
            onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
            type="button"
          >
            <span className="theme-toggle__icon" aria-hidden="true">
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </span>
            <span>{theme === 'dark' ? '日间' : '夜间'}</span>
          </button>
          <span className="system-status"><i /> UNIFIED INDEX ONLINE</span>
        </nav>
      </header>

      <SearchWorkspace query={query} onQueryChange={setQuery} onSelectMaterial={setSelectedMaterial} />

      {selectedMaterial && <MaterialDetail materialId={selectedMaterial} onClose={() => setSelectedMaterial(null)} />}

      <footer className="site-footer">
        <div><Atom size={17} /><span>MateriaViva</span></div>
        <p>MateriaViva · 多源晶体数据统一整合、去重与检索。</p>
        <a href="https://github.com" aria-label="GitHub"><Github size={17} /></a>
      </footer>
    </div>
  )
}
