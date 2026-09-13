import { useEffect, useState, type ReactNode } from 'react'
import { Activity, Beaker, DatabaseZap, FlaskConical, Layers3, RotateCcw, Search, SlidersHorizontal, X } from 'lucide-react'

import { DEFAULT_QUERY, type MaterialQuery } from '../lib/query'
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

function exact(value: number | null | undefined, locale: string): string {
  return value === null || value === undefined ? '—' : value.toLocaleString(locale)
}

export function SearchWorkspace({ query, onQueryChange, onSelectMaterial }: SearchWorkspaceProps) {
  const { t, locale } = useI18n()
  const { data, error, loading, refresh } = useMaterials(query)
  const { data: stats, status: statsStatus } = useAtlasStats()
  const [filtersOpen, setFiltersOpen] = useState(() => typeof window === 'undefined' || typeof window.matchMedia !== 'function' || window.matchMedia('(min-width: 761px)').matches)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const viewport = window.matchMedia('(min-width: 761px)')
    const sync = () => { if (viewport.matches) setFiltersOpen(true) }
    viewport.addEventListener('change', sync)
    return () => viewport.removeEventListener('change', sync)
  }, [])
  useEffect(() => {
    if (data && data.pages > 0 && query.page > data.pages) {
      onQueryChange({ ...query, page: data.pages })
    }
  }, [data, onQueryChange, query])
  const subtitleKey = statsStatus !== 'ready'
    ? 'hero.subtitleFallback'
    : stats?.property_rows === null || stats?.property_rows === undefined
      ? 'hero.subtitleNoProps'
      : 'hero.subtitle'
  const selection: ElementSelection = Object.fromEntries([
    ...query.includedElements.map((symbol) => [symbol, 'include']),
    ...query.excludedElements.map((symbol) => [symbol, 'exclude']),
  ])
  const selectedElementCount = query.includedElements.length + query.excludedElements.length
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
          <h1 className="hero__title">
            <span>{t('hero.titleLead')}</span>
            <em>{t('hero.titleEm')}</em>
          </h1>
          <p>{t(subtitleKey)}</p>
          <label className="hero-search">
            <span>{t('hero.searchLabel')}</span>
            <div><Search size={18} aria-hidden="true" /><input value={query.formula} onChange={(event) => onQueryChange({ ...query, formula: event.target.value, page: 1 })} placeholder={t('hero.searchPlaceholder')} /></div>
          </label>
        </div>
        <div className="hero__metrics" aria-label={t('hero.metricsLabel')} data-status={statsStatus}>
          {statsStatus === 'error' ? (
            <div className="metrics-error"><DatabaseZap /><span><strong>{t('stats.unavailable')}</strong><small>{t('stats.unavailableBody')}</small></span></div>
          ) : (
            <>
              <Metric icon={<FlaskConical />} loadingLabel={t('status.loading')} pending={statsStatus === 'loading'} value={exact(stats?.datasets?.experimental, locale)} label={t('metric.experimental')} tone="mint" />
              <Metric icon={<Layers3 />} loadingLabel={t('status.loading')} pending={statsStatus === 'loading'} value={exact(stats?.datasets?.candidate, locale)} label={t('metric.candidate')} tone="orange" />
              <Metric icon={<DatabaseZap />} loadingLabel={t('status.loading')} pending={statsStatus === 'loading'} value={exact(stats?.total, locale)} label={t('metric.index')} tone="plain" />
            </>
          )}
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
        <p className="lab-guidance">{t('lab.guidance')}</p>
        <PeriodicTable selection={selection} onChange={changeSelection} />
        <div className="element-lab__footer">
          <div className="selection-summary">
            <div className="selection-readout">
              <span>{t('readout.in')}</span><strong>{[...query.includedElements].sort().join(' · ') || t('readout.anyElement')}</strong>
              <span>{t('readout.out')}</span><strong>{[...query.excludedElements].sort().join(' · ') || t('readout.none')}</strong>
            </div>
            {selectedElementCount > 0 && (
              <button className="selection-clear" type="button" onClick={() => onQueryChange({ ...query, includedElements: [], excludedElements: [], page: 1 })}>
                <RotateCcw size={13} /> {t('lab.clear')}
              </button>
            )}
          </div>
          <div className="mode-switch" aria-label={t('mode.label')}>
            {([['all', 'mode.all'], ['any', 'mode.any'], ['exact', 'mode.exact']] as const).map(([value, label]) => (
              <button aria-pressed={query.elementMode === value} data-active={query.elementMode === value} key={value} onClick={() => onQueryChange({ ...query, elementMode: value, page: 1 })} type="button">{t(label)}</button>
            ))}
          </div>
        </div>
      </section>

      <section className={`catalog${filtersOpen ? '' : ' catalog--filters-closed'}`} aria-labelledby="catalog-title">
        <aside>
          <details className="filters-disclosure" open={filtersOpen} onToggle={(event) => setFiltersOpen(event.currentTarget.open)}>
            <summary><span><SlidersHorizontal size={16} />{t('filters.open')}</span><small>{countAllFilters(query) || t('filters.none')}</small></summary>
            <AdvancedFilters query={query} onChange={onQueryChange} />
          </details>
        </aside>
        <div className="catalog__results">
          <div className="results-toolbar">
            <div>
              <span className="eyebrow"><Beaker size={13} /> {t('catalog.eyebrow')}</span>
              <h2 id="catalog-title" aria-live="polite">{data && !error ? data.total.toLocaleString(locale) : loading ? '…' : '—'} <small>{t('catalog.results')}</small></h2>
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
          <ActiveFilterBar query={query} onChange={onQueryChange} />
          <MaterialResults
            data={data}
            error={error}
            loading={loading}
            onPage={(page) => { onQueryChange({ ...query, page }); const top = document.querySelector('.catalog')?.getBoundingClientRect().top ?? 0; window.scrollTo({ top: window.scrollY + top - 84, behavior: 'smooth' }) }}
            onRetry={refresh}
            onSelect={onSelectMaterial}
          />
        </div>
      </section>
    </main>
  )
}

function ActiveFilterBar({ query, onChange }: { query: MaterialQuery; onChange: (query: MaterialQuery) => void }) {
  const { t } = useI18n()
  const tags: Array<{ label: string; clear: Partial<MaterialQuery> }> = []
  if (query.formula) tags.push({ label: query.formula, clear: { formula: '' } })
  if (query.includedElements.length) tags.push({ label: `${t('legend.include')}: ${query.includedElements.join(' · ')}`, clear: { includedElements: [] } })
  if (query.excludedElements.length) tags.push({ label: `${t('legend.exclude')}: ${query.excludedElements.join(' · ')}`, clear: { excludedElements: [] } })
  if (query.datasets.length) tags.push({ label: query.datasets[0] === 'experimental' ? t('filters.experimental') : t('filters.candidate'), clear: { datasets: [] } })
  query.crystalSystems.forEach((value) => tags.push({ label: t(`system.${value}` as Parameters<typeof t>[0]), clear: { crystalSystems: query.crystalSystems.filter((item) => item !== value) } }))
  query.materialFamilies.forEach((value) => tags.push({ label: t(`family.${value}` as Parameters<typeof t>[0]), clear: { materialFamilies: query.materialFamilies.filter((item) => item !== value) } }))
  const advancedCount = countAdvancedFilters(query)
  if (advancedCount) tags.push({ label: t('filters.moreActive', { count: String(advancedCount) }), clear: clearAdvanced() })
  if (!tags.length) return <p className="active-filters active-filters--empty">{t('filters.noneActive')}</p>
  return (
    <div className="active-filters" aria-label={t('filters.active')}>
      <span>{t('filters.active')}</span>
      <div>{tags.map((tag, index) => <button key={`${tag.label}-${index}`} onClick={() => onChange({ ...query, ...tag.clear, page: 1 })} type="button">{tag.label}<X size={12} /></button>)}</div>
      <button className="active-filters__clear" onClick={() => onChange({ ...DEFAULT_QUERY, pageSize: query.pageSize, sort: query.sort, direction: query.direction })} type="button">{t('filters.clearAll')}</button>
    </div>
  )
}

function countAdvancedFilters(query: MaterialQuery) {
  return [query.gapMin, query.gapMax, query.densityMin, query.densityMax, query.nAtomsMin, query.nAtomsMax,
    query.nElementsMin, query.nElementsMax, query.volumeMin, query.volumeMax, query.formationEnergyMin,
    query.formationEnergyMax, query.energyAboveHullMin, query.energyAboveHullMax, query.magnetizationMin,
    query.magnetizationMax, query.bulkModulusMin, query.bulkModulusMax, query.shearModulusMin, query.shearModulusMax]
    .filter((value) => value !== undefined).length
    + [query.spacegroups, query.stability, query.metallicity, query.magneticOrderings].filter(Boolean).length
    + query.hasProperties.length
}

function clearAdvanced(): Partial<MaterialQuery> {
  return {
    gapMin: undefined, gapMax: undefined, densityMin: undefined, densityMax: undefined,
    nAtomsMin: undefined, nAtomsMax: undefined, nElementsMin: undefined, nElementsMax: undefined,
    volumeMin: undefined, volumeMax: undefined, formationEnergyMin: undefined, formationEnergyMax: undefined,
    energyAboveHullMin: undefined, energyAboveHullMax: undefined, magnetizationMin: undefined,
    magnetizationMax: undefined, bulkModulusMin: undefined, bulkModulusMax: undefined,
    shearModulusMin: undefined, shearModulusMax: undefined, spacegroups: '', stability: '', metallicity: '',
    magneticOrderings: '', hasProperties: [],
  }
}

function countAllFilters(query: MaterialQuery) {
  return query.includedElements.length + query.excludedElements.length + query.datasets.length + query.crystalSystems.length
    + query.materialFamilies.length + (query.formula ? 1 : 0) + countAdvancedFilters(query)
}

function Metric({ icon, value, label, tone, pending, loadingLabel }: { icon: ReactNode; value: string; label: string; tone: string; pending: boolean; loadingLabel: string }) {
  return (
    <div className="metric" data-pending={pending} data-tone={tone}>
      <span className="metric__icon">{icon}</span>
      <span className="metric__copy"><small>{label}</small><strong>{pending ? <i aria-label={loadingLabel} /> : value}</strong></span>
    </div>
  )
}
