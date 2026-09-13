import { useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ChevronDown, Database, FlaskConical, Search, X } from 'lucide-react'

import {
  getMaterial,
  getStructure,
  type CrystalStructure,
  type MaterialDetailRecord,
  type MaterialProperty,
  type MaterialSourceRef,
} from '../api/client'
import { useAtlasStats } from '../hooks/useMaterials'
import { collapseIdenticalRows } from '../lib/crystal'
import { Formula, formulaText } from './Formula'
import { useI18n, type TranslationKey } from '../i18n'
import { CrystalViewer } from './CrystalViewer'
import { SpectraPanel } from './SpectraPanel'

interface MaterialDetailProps {
  materialId: string
  onClose: () => void
}

export function MaterialDetail({ materialId, onClose }: MaterialDetailProps) {
  const { t } = useI18n()
  const [material, setMaterial] = useState<MaterialDetailRecord | null>(null)
  const [structure, setStructure] = useState<CrystalStructure | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const closeRef = useRef<HTMLButtonElement | null>(null)
  // false when the server has no OVITO worker; the viewer must not open on that tab
  const ovitoAvailable = useAtlasStats().data?.ovito_available ?? true

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    window.requestAnimationFrame(() => closeRef.current?.focus())
    const controller = new AbortController()
    setMaterial(null)
    setStructure(null)
    setError(null)
    Promise.all([getMaterial(materialId, controller.signal), getStructure(materialId, controller.signal)])
      .then(([nextMaterial, nextStructure]) => { setMaterial(nextMaterial); setStructure(nextStructure) })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        setError(reason instanceof Error ? reason.message : t('detail.loadFailed'))
      })
    const previousOverflow = document.body.style.overflow
    const background = Array.from(document.querySelectorAll<HTMLElement>('.app-shell > :not(.detail-shell)'))
      .map((element) => [element, element.inert] as const)
    background.forEach(([element]) => { element.inert = true })
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      controller.abort()
      document.body.style.overflow = previousOverflow
      background.forEach(([element, inert]) => { element.inert = inert })
      window.removeEventListener('keydown', onKeyDown)
      previousFocus?.focus()
    }
  }, [materialId, onClose, revision, t])

  return (
    <div className="detail-shell" role="dialog" aria-modal="true" aria-label={t('detail.label')}>
      <button className="detail-close" ref={closeRef} aria-label={t('detail.close')} onClick={onClose} type="button"><X /></button>
      {error ? (
        <div className="detail-state" role="alert"><strong>{t('detail.workbenchFailed')}</strong><p>{error}</p><button type="button" onClick={() => setRevision((value) => value + 1)}>{t('detail.retry')}</button></div>
      ) : !material || !structure ? (
        <div className="detail-state"><span className="scanner" /><strong>{t('detail.parsing')}</strong><p>{materialId}</p></div>
      ) : (
        <article className="detail-workbench">
          <header className="detail-heading">
            <div>
              <span className={`source-badge source-badge--${material.dataset}`}>
                {material.is_experimental ? <FlaskConical size={13} /> : <Database size={13} />}
                {material.is_experimental ? t('badge.experimental') : t('badge.candidate')}
              </span>
              {material.material_family ? (
                <span className="family-badge" data-family={material.material_family}>
                  {t(`family.${material.material_family}` as TranslationKey)}
                </span>
              ) : null}
              <h1 aria-label={formulaText(material.formula)}><Formula value={material.formula} /></h1>
              <p>{material.material_id} <i /> {material.chemical_system}</p>
            </div>
            <a className="download-button" href={`/api/materials/${encodeURIComponent(materialId)}/cif`} download>
              <ArrowDownToLine size={16} /> {t('detail.downloadCif')}
            </a>
          </header>

          <div className="detail-layout">
            <div className="detail-visual-column">
              <CrystalViewer materialId={materialId} structure={structure} ovitoAvailable={ovitoAvailable} />
              <RepresentativeProperties material={material} />
            </div>
            <aside className="material-inspector">
              <div className="inspector-ruler"><span>{t('detail.record')}</span><b>{material.material_id}</b></div>
              <PropertySection title={t('detail.basic')}>
                <Property label={t('detail.spacegroup')} value={material.spacegroup_symbol && material.spacegroup_number ? `${material.spacegroup_symbol} · ${material.spacegroup_number}` : material.spacegroup_number} />
                <Property label={t('detail.crystalSystem')} value={material.crystal_system ? t(`system.${material.crystal_system}` as TranslationKey) : null} />
                <Property label={t('detail.gap')} value={unit(material.pbes_gap, 'eV', 3)} />
                <Property label={t('detail.density')} value={unit(material.density, 'g·cm⁻³', 3)} />
                <Property label={t('detail.atoms')} value={material.n_atoms} />
                <Property label={t('detail.volume')} value={unit(material.volume ?? structure.lattice.volume, 'Å³', 3)} />
              </PropertySection>
              <PropertySection title={t('detail.lattice')}>
                <Property label="a / b / c" value={`${fixed(material.lattice_a ?? structure.lattice.a)} / ${fixed(material.lattice_b ?? structure.lattice.b)} / ${fixed(material.lattice_c ?? structure.lattice.c)} Å`} wide />
                <Property label="α / β / γ" value={`${fixed(material.lattice_alpha ?? structure.lattice.alpha, 2)} / ${fixed(material.lattice_beta ?? structure.lattice.beta, 2)} / ${fixed(material.lattice_gamma ?? structure.lattice.gamma, 2)}°`} wide />
              </PropertySection>
              <PropertySection title={t('detail.composition')}>
                <div className="element-tags">{material.elements.map((element) => <span key={element}>{element}</span>)}</div>
              </PropertySection>
              <PropertySection title={t('detail.provenance')}>
                <p className="provenance">{t('detail.dataset')}: {material.source_split === 'train' ? t('detail.trainingSet') : material.source_split} · {t('detail.recordNumber')}: {material.source_index}</p>
                <p className="provenance-note">{t('detail.provenanceNote')}</p>
              </PropertySection>
            </aside>
          </div>

          <div className="detail-sections">
            <DeferredSection title={t('spectra.label')} count={(material.curves?.length ?? 0) + 1}>
              <SpectraPanel curves={material.curves ?? []} materialId={materialId} />
            </DeferredSection>
            <DeferredSection title={t('detail.crossdb')} count={material.properties?.length ?? 0}>
              <CrossDatabaseProperties properties={material.properties ?? []} />
            </DeferredSection>
            <SourceRefs refs={material.source_refs ?? []} />
          </div>
        </article>
      )}
    </div>
  )
}

function DeferredSection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <section className="detail-disclosure">
      <button aria-expanded={open} onClick={() => setOpen((value) => !value)} type="button">
        <span><strong>{title}</strong><small>{count}</small></span><ChevronDown size={18} />
      </button>
      {open && <div className="detail-disclosure__body">{children}</div>}
    </section>
  )
}

function PropertySection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="property-section"><h2>{title}</h2><div className="property-section__grid">{children}</div></section>
}

function RepresentativeProperties({ material }: { material: MaterialDetailRecord }) {
  const { t } = useI18n()
  const optional = (value: number | null | undefined, suffix: string, digits: number) =>
    value == null ? null : `${value.toFixed(digits)} ${suffix}`
  const rows: Array<[string, string | number | null | undefined]> = [
    [t('detail.formationEnergy'), optional(material.formation_energy_per_atom, 'eV/atom', 3)],
    [t('detail.hull'), optional(material.energy_above_hull, 'eV/atom', 3)],
    [t('detail.stability'), material.is_stable == null ? null : material.is_stable ? t('detail.stable') : t('detail.unstable')],
    [t('detail.metallicity'), material.is_metal == null ? null : material.is_metal ? t('detail.metal') : t('detail.nonmetal')],
    [t('detail.magneticOrdering'), material.magnetic_ordering],
    [t('detail.magnetization'), optional(material.total_magnetization, 'μB', 3)],
    [t('detail.bulkModulus'), optional(material.bulk_modulus, 'GPa', 1)],
    [t('detail.shearModulus'), optional(material.shear_modulus, 'GPa', 1)],
    [t('detail.poisson'), material.poisson_ratio == null ? null : material.poisson_ratio.toFixed(3)],
  ]
  const present = rows.filter(([, value]) => value != null)
  return (
    <PropertySection title={t('detail.representative')}>
      {present.length > 0
        ? present.map(([label, value]) => <Property key={label} label={label} value={value} />)
        : <p className="provenance-note">{t('detail.noRepresentative')}</p>}
    </PropertySection>
  )
}

function prettyPropertyName(name: string, lang: string) {
  const normalized = name.replace(/_/g, ' ')
  if (lang !== 'zh') return normalized
  const names: Record<string, string> = {
    'band gap': '带隙', density: '密度', volume: '晶胞体积', 'space group': '空间群',
    'formation energy': '形成能', 'energy above hull': '凸包能', magnetization: '磁矩',
    'bulk modulus': '体积模量', 'shear modulus': '剪切模量', 'poisson ratio': '泊松比',
    'average oxidation states': '平均氧化态',
  }
  return names[normalized.toLowerCase()] ?? normalized
}

function formatPropertyValue(row: MaterialProperty, lang: string) {
  if (row.kind === 'bool' && row.value_num != null) return row.value_num ? (lang === 'zh' ? '是' : 'yes') : (lang === 'zh' ? '否' : 'no')
  if (row.value_num != null) {
    const magnitude = Math.abs(row.value_num)
    const digits = magnitude !== 0 && (magnitude < 0.01 || magnitude >= 100000) ? undefined : 4
    const text = digits === undefined ? row.value_num.toExponential(3) : Number(row.value_num.toFixed(digits)).toString()
    return row.unit ? `${text} ${row.unit}` : text
  }
  return row.value_text ?? '—'
}

function CrossDatabaseProperties({ properties }: { properties: MaterialProperty[] }) {
  const { t, lang } = useI18n()
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState(false)
  const rows = collapseIdenticalRows(properties).filter(({ row }) => {
    const term = search.trim().toLowerCase()
    return !term || `${row.property} ${row.method ?? ''} ${row.source_name}`.toLowerCase().includes(term)
  })
  const visibleRows = expanded ? rows : rows.slice(0, 30)
  return (
    <section className="property-section property-section--crossdb">
      <h2>{t('detail.crossdb')}</h2>
      {properties.length === 0 ? (
        <p className="provenance-note">{t('detail.noProperties')}</p>
      ) : (
        <>
          <p className="provenance-note">{t('detail.crossdbNote')}</p>
          <label className="property-search"><Search size={15} /><input aria-label={t('detail.searchProperties')} placeholder={t('detail.searchProperties')} value={search} onChange={(event) => setSearch(event.target.value)} /></label>
          <div className="crossdb-scroll">
            <table className="crossdb-table">
              <thead>
                <tr>
                  <th>{t('detail.property')}</th>
                  <th>{t('detail.value')}</th>
                  <th>{t('detail.method')}</th>
                  <th>{t('detail.source')}</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.length === 0 ? (
                  <tr><td className="crossdb-table__empty" colSpan={4}>{t('detail.noPropertyMatches')}</td></tr>
                ) : visibleRows.map(({ row, count, nativeIds }, index) => (
                  <tr key={index}>
                    <td>{prettyPropertyName(row.property, lang)}</td>
                    <td className="crossdb-table__value">{formatPropertyValue(row, lang)}</td>
                    <td className="crossdb-table__method">{row.method ?? '—'}</td>
                    <td className="crossdb-table__source" title={row.source_license ?? undefined}>
                      {row.source_name}
                      {count > 1 && (
                        // one source can hold many records for one crystal; they were
                        // printed as identical rows, which reads as a bug rather than data
                        <span className="crossdb-table__repeat" title={nativeIds.join('\n')}>
                          ×{count}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length > 30 && <button className="show-properties" type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? t('detail.showLess') : t('detail.showMore', { count: String(rows.length - 30) })}</button>}
        </>
      )}
    </section>
  )
}

function SourceRefs({ refs }: { refs: MaterialSourceRef[] }) {
  const { t } = useI18n()
  if (refs.length === 0) return null
  const viaLabel = (via: string) =>
    via === 'origin' ? t('detail.viaOrigin') : via === 'hash' ? t('detail.viaHash') : t('detail.viaId')
  return (
    <section className="property-section">
      <h2>{t('detail.sources')}</h2>
      <ul className="sourceref-list">
        {refs.map((ref, index) => (
          <li key={index} title={`${viaLabel(ref.match_via)}${ref.source_license ? ` · ${ref.source_license}` : ''}`}>
            {ref.source_url ? (
              <a href={ref.source_url} rel="noreferrer" target="_blank">{ref.source_name}</a>
            ) : (
              <span>{ref.source_name}</span>
            )}
            <code>{ref.native_id}</code>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Property({ label, value, wide = false }: { label: string; value: string | number | null | undefined; wide?: boolean }) {
  return <dl className={wide ? 'wide' : ''}><dt>{label}</dt><dd>{value ?? '—'}</dd></dl>
}

function fixed(value: number | null | undefined, digits = 3) {
  return value == null ? '—' : value.toFixed(digits)
}

function unit(value: number | null | undefined, suffix: string, digits: number) {
  return value == null ? '—' : `${value.toFixed(digits)} ${suffix}`
}
