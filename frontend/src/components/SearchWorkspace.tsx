import type { ReactNode } from 'react'
import { Activity, Beaker, DatabaseZap, FlaskConical, Layers3 } from 'lucide-react'

import type { MaterialQuery } from '../lib/query'
import { useAtlasStats, useMaterials } from '../hooks/useMaterials'
import { useI18n } from '../i18n'
import { AdvancedFilters } from './AdvancedFilters'
import { MaterialResults } from './MaterialResults'
import { PeriodicTable, type ElementSelection } from './PeriodicTable'

interface SearchWorkspaceProps {
  query: MaterialQuery
  onQueryChange: (query: MaterialQuery) => void
  onSelectMaterial: (materialId: string) => void
}

/** Big counts in prose, in each language's own idiom. */
function approx(value: number | null | undefined, locale: string): string {
  if (value === null || value === undefined) return '—'
  if (locale.startsWith('zh')) {
    // No Intl notation produces 亿/万, so the split is explicit.
    if (value >= 1e8) return `${(value / 1e8).toFixed(2)} 亿`
    if (value >= 1e4) return `${(value / 1e4).toFixed(1)} 万`
    return value.toLocaleString(locale)
  }
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)} million`
  return value.toLocaleString(locale)
}

function exact(value: number | null | undefined, locale: string): string {
  return value === null || value === undefined ? '—' : value.toLocaleString(locale)
}

export function SearchWorkspace({ query, onQueryChange, onSelectMaterial }: SearchWorkspaceProps) {
  const { t, locale } = useI18n()
  const { data, error, loading, refresh } = useMaterials(query)
  const stats = useAtlasStats()
  // Every figure in the hero comes from /api/stats. They used to be literals in
  // the copy and each one drifted as the pool grew -- at one point the page
  // showed a hardcoded "99,162 experimental" beside a live 13,504,703 index.
  const heroNumbers = {
    total: approx(stats?.total, locale),
    experimental: locale.startsWith('zh')
      ? approx(stats?.datasets?.experimental, locale)
      : exact(stats?.datasets?.experimental, locale),
    candidate: locale.startsWith('zh')
      ? approx(stats?.datasets?.candidate, locale)
      : exact(stats?.datasets?.candidate, locale),
    properties: approx(stats?.property_rows, locale),
  }
  const subtitleKey =
    stats?.property_rows === null || stats?.property_rows === undefined
      ? 'hero.subtitleNoProps'
      : 'hero.subtitle'
  const selection: ElementSelection = Object.fromEntries([
    ...query.includedElements.map((symbol) => [symbol, 'include']),
    ...query.excludedElements.map((symbol) => [symbol, 'exclude']),
  ])
  const changeSelection = (next: ElementSelection) => {
    const includedElements = Object.entries(next).filter(([, state]) => state === 'include').map(([symbol]) => symbol)
    const excludedElements = Object.entries(next).filter(([, state]) => state === 'exclude').map(([symbol]) => symbol)
    onQueryChange({ ...query, includedElements, excludedElements, page: 1 })
  }

  return (
    <main>
      <section className="hero">
        <div className="hero__copy">
          <span className="eyebrow"><Activity size={13} /> {t('hero.eyebrow')}</span>
          <h1>{t('hero.titleLead')}<br /><em>{t('hero.titleEm', heroNumbers)}</em></h1>
          <p>{t(subtitleKey, heroNumbers)}</p>
        </div>
        <div className="hero__metrics" aria-label={t('hero.metricsLabel')}>
          <Metric icon={<FlaskConical />} value={exact(stats?.datasets?.experimental, locale)} label={t('metric.experimental')} tone="mint" />
          <Metric icon={<Layers3 />} value={exact(stats?.datasets?.candidate, locale)} label={t('metric.candidate')} tone="orange" />
          <Metric icon={<DatabaseZap />} value={exact(stats?.total, locale)} label={t('metric.index')} tone="plain" />
        </div>
      </section>

      <section className="element-lab" aria-labelledby="element-lab-title">
        <div className="section-ruler"><span>CHEMICAL SPACE</span><b>01—118</b></div>
        <div className="element-lab__heading">
          <div><span className="eyebrow">{t('lab.eyebrow')}</span><h2 id="element-lab-title">{t('lab.title')}</h2></div>
          <div className="element-legend">
            <span><i data-tone="include" />{t('legend.include')}</span><span><i data-tone="exclude" />{t('legend.exclude')}</span><span><i />{t('legend.unselected')}</span>
          </div>
        </div>
        <PeriodicTable selection={selection} onChange={changeSelection} />
        <div className="element-lab__footer">
          <div className="selection-readout">
            <span>IN</span><strong>{[...query.includedElements].sort().join(' · ') || t('readout.anyElement')}</strong>
            <span>OUT</span><strong>{[...query.excludedElements].sort().join(' · ') || t('readout.none')}</strong>
          </div>
          <div className="mode-switch" aria-label={t('mode.label')}>
            {([['all', 'mode.all'], ['any', 'mode.any'], ['exact', 'mode.exact']] as const).map(([value, label]) => (
              <button data-active={query.elementMode === value} key={value} onClick={() => onQueryChange({ ...query, elementMode: value, page: 1 })} type="button">{t(label)}</button>
            ))}
          </div>
        </div>
      </section>

      <section className="catalog" aria-labelledby="catalog-title">
        <aside><AdvancedFilters query={query} onChange={onQueryChange} onApply={refresh} /></aside>
        <div className="catalog__results">
          <div className="results-toolbar">
            <div>
              <span className="eyebrow"><Beaker size={13} /> {t('catalog.eyebrow')}</span>
              <h2 id="catalog-title">{data ? data.total.toLocaleString(locale) : '—'} <small>{t('catalog.results')}</small></h2>
            </div>
            <label>{t('catalog.sort')}
              <select value={`${query.sort}:${query.direction}`} onChange={(event) => {
                const [sort, direction] = event.target.value.split(':')
                onQueryChange({ ...query, sort, direction: direction as 'asc' | 'desc', page: 1 })
              }}>
                <option value="material_id:asc">{t('sort.materialId')}</option>
                <option value="formula:asc">{t('sort.formula')}</option>
                <option value="pbes_gap:desc">{t('sort.gap')}</option>
                <option value="density:desc">{t('sort.density')}</option>
                <option value="n_atoms:asc">{t('sort.atoms')}</option>
                <option value="volume:asc">{t('sort.volume')}</option>
                <option value="formation_energy_per_atom:asc">{t('sort.formationEnergy')}</option>
                <option value="energy_above_hull:asc">{t('sort.hull')}</option>
                <option value="spacegroup_number:asc">{t('sort.spacegroup')}</option>
              </select>
            </label>
          </div>
          <MaterialResults
            data={data}
            error={error}
            loading={loading}
            onPage={(page) => { onQueryChange({ ...query, page }); window.scrollTo({ top: document.querySelector('.catalog')?.getBoundingClientRect().top ?? 0, behavior: 'smooth' }) }}
            onRetry={refresh}
            onSelect={onSelectMaterial}
          />
        </div>
      </section>
    </main>
  )
}

function Metric({ icon, value, label, tone }: { icon: ReactNode; value: string; label: string; tone: string }) {
  return <div className="metric" data-tone={tone}><span>{icon}</span><strong>{value}</strong><small>{label}</small></div>
}
