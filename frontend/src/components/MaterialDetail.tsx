import { useEffect, useState } from 'react'
import { ArrowDownToLine, Database, FlaskConical, X } from 'lucide-react'

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
  // false when the server has no OVITO worker; the viewer must not open on that tab
  const ovitoAvailable = useAtlasStats()?.ovito_available ?? true

  useEffect(() => {
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
    document.body.style.overflow = 'hidden'
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      controller.abort()
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [materialId, onClose, t])

  return (
    <div className="detail-shell" role="dialog" aria-modal="true" aria-label={t('detail.label')}>
      <button className="detail-close" aria-label={t('detail.close')} onClick={onClose} type="button"><X /></button>
      {error ? (
        <div className="detail-state" role="alert"><strong>{t('detail.workbenchFailed')}</strong><p>{error}</p></div>
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
              <h1 aria-label={material.formula}><Formula value={material.formula} /></h1>
              <p>{material.material_id} <i /> {material.chemical_system}</p>
            </div>
            <a className="download-button" href={`/api/materials/${encodeURIComponent(materialId)}/cif`} download>
              <ArrowDownToLine size={16} /> {t('detail.downloadCif')}
            </a>
          </header>

          <div className="detail-layout">
            <CrystalViewer materialId={materialId} structure={structure} ovitoAvailable={ovitoAvailable} />
            <aside className="material-inspector">
              <div className="inspector-ruler"><span>MATERIAL RECORD</span><b>{material.material_id}</b></div>
              <PropertySection title={t('detail.basic')}>
                <Property label={t('detail.spacegroup')} value={material.spacegroup_symbol && material.spacegroup_number ? `${material.spacegroup_symbol} · ${material.spacegroup_number}` : material.spacegroup_number} />
                <Property label={t('detail.crystalSystem')} value={material.crystal_system} />
                <Property label={t('detail.gap')} value={unit(material.pbes_gap, 'eV', 3)} />
                <Property label={t('detail.density')} value={unit(material.density, 'g cm⁻³', 3)} />
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
                <p className="provenance">{material.source_split} · row {material.source_index}</p>
                <p className="provenance-note">{t('detail.provenanceNote')}</p>
              </PropertySection>
            </aside>
          </div>

          <div className="detail-sections">
            <RepresentativeProperties material={material} />
            <SpectraPanel curves={material.curves ?? []} materialId={materialId} />
            <CrossDatabaseProperties properties={material.properties ?? []} />
            <SourceRefs refs={material.source_refs ?? []} />
          </div>
        </article>
      )}
    </div>
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
  if (present.length === 0) return null
  return (
    <PropertySection title={t('detail.representative')}>
      {present.map(([label, value]) => <Property key={label} label={label} value={value} />)}
    </PropertySection>
  )
}

function prettyPropertyName(name: string) {
  return name.replace(/_/g, ' ')
}

function formatPropertyValue(row: MaterialProperty) {
  if (row.kind === 'bool' && row.value_num != null) return row.value_num ? 'yes' : 'no'
  if (row.value_num != null) {
    const magnitude = Math.abs(row.value_num)
    const digits = magnitude !== 0 && (magnitude < 0.01 || magnitude >= 100000) ? undefined : 4
    const text = digits === undefined ? row.value_num.toExponential(3) : Number(row.value_num.toFixed(digits)).toString()
    return row.unit ? `${text} ${row.unit}` : text
  }
  return row.value_text ?? '—'
}

function CrossDatabaseProperties({ properties }: { properties: MaterialProperty[] }) {
  const { t } = useI18n()
  return (
    <section className="property-section property-section--crossdb">
      <h2>{t('detail.crossdb')}</h2>
      {properties.length === 0 ? (
        <p className="provenance-note">{t('detail.noProperties')}</p>
      ) : (
        <>
          <p className="provenance-note">{t('detail.crossdbNote')}</p>
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
                {collapseIdenticalRows(properties).map(({ row, count, nativeIds }, index) => (
                  <tr key={index}>
                    <td>{prettyPropertyName(row.property)}</td>
                    <td className="crossdb-table__value">{formatPropertyValue(row)}</td>
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

function Formula({ value }: { value: string }) {
  return <>{value.split(/(\d+(?:\.\d+)?)/g).map((part, index) => /^\d/.test(part) ? <sub key={index}>{part}</sub> : part)}</>
}

function fixed(value: number | null | undefined, digits = 3) {
  return value == null ? '—' : value.toFixed(digits)
}

function unit(value: number | null | undefined, suffix: string, digits: number) {
  return value == null ? '—' : `${value.toFixed(digits)} ${suffix}`
}
