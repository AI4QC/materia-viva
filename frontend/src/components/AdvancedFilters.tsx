import { ChevronDown, Filter, RotateCcw, Search } from 'lucide-react'

import { useI18n, type TranslationKey } from '../i18n'
import type { MaterialQuery } from '../lib/query'

interface AdvancedFiltersProps {
  query: MaterialQuery
  onChange: (query: MaterialQuery) => void
  onApply: () => void
}

const CRYSTAL_SYSTEMS = [
  'triclinic', 'monoclinic', 'orthorhombic', 'tetragonal', 'trigonal', 'hexagonal', 'cubic',
] as const

const PROPERTY_OPTIONS = [
  'band_gap', 'density', 'spacegroup', 'formation_energy', 'energy_above_hull',
  'magnetism', 'elasticity',
] as const

const MATERIAL_FAMILIES = [
  'bulk', 'mof', 'cof', 'hof', 'zeolite', 'zeotype', 'molecular-crystal',
  '2d-material', '1d-material', 'carbon-allotrope',
] as const

export function AdvancedFilters({ query, onChange, onApply }: AdvancedFiltersProps) {
  const { t } = useI18n()
  const update = (patch: Partial<MaterialQuery>) => onChange({ ...query, ...patch, page: 1 })
  const toggleDataset = (dataset: 'experimental' | 'candidate') => {
    const datasets = query.datasets.includes(dataset)
      ? query.datasets.filter((value) => value !== dataset)
      : [...query.datasets, dataset]
    update({ datasets })
  }
  const toggleSystem = (system: string) => {
    const crystalSystems = query.crystalSystems.includes(system)
      ? query.crystalSystems.filter((value) => value !== system)
      : [...query.crystalSystems, system]
    update({ crystalSystems })
  }
  const toggleProperty = (property: string) => {
    const hasProperties = query.hasProperties.includes(property)
      ? query.hasProperties.filter((value) => value !== property)
      : [...query.hasProperties, property]
    update({ hasProperties })
  }
  const toggleFamily = (family: string) => {
    const materialFamilies = query.materialFamilies.includes(family)
      ? query.materialFamilies.filter((value) => value !== family)
      : [...query.materialFamilies, family]
    update({ materialFamilies })
  }
  const reset = () => onChange({
    ...query,
    datasets: [], formula: '', gapMin: undefined, gapMax: undefined,
    densityMin: undefined, densityMax: undefined, nAtomsMin: undefined,
    nAtomsMax: undefined, nElementsMin: undefined, nElementsMax: undefined,
    volumeMin: undefined, volumeMax: undefined,
    formationEnergyMin: undefined, formationEnergyMax: undefined,
    energyAboveHullMin: undefined, energyAboveHullMax: undefined,
    stability: '', metallicity: '', magneticOrderings: '', materialFamilies: [],
    magnetizationMin: undefined, magnetizationMax: undefined,
    bulkModulusMin: undefined, bulkModulusMax: undefined,
    shearModulusMin: undefined, shearModulusMax: undefined,
    hasProperties: [],
    spacegroups: '', crystalSystems: [], page: 1,
  })

  return (
    <form className="filters" onSubmit={(event) => { event.preventDefault(); onApply() }}>
      <div className="filters__heading">
        <div>
          <span className="eyebrow"><Filter size={13} /> {t('filters.eyebrow')}</span>
          <h2>{t('filters.title')}</h2>
        </div>
        <button className="icon-button" type="button" onClick={reset} aria-label={t('filters.reset')}>
          <RotateCcw size={16} />
        </button>
      </div>

      <label className="field">
        <span>{t('filters.formulaLabel')}</span>
        <div className="input-with-icon">
          <Search size={15} aria-hidden="true" />
          <input
            aria-label={t('filters.formulaLabel')}
            onChange={(event) => update({ formula: event.target.value })}
            placeholder={t('filters.formulaPlaceholder')}
            value={query.formula}
          />
        </div>
      </label>

      <fieldset className="field-group">
        <legend>{t('filters.datasets')}</legend>
        <label className="check-row">
          <input checked={query.datasets.includes('experimental')} onChange={() => toggleDataset('experimental')} type="checkbox" />
          <span><i className="source-dot source-dot--exp" />{t('filters.experimentalOnly')}</span>
        </label>
        <label className="check-row">
          <input checked={query.datasets.includes('candidate')} onChange={() => toggleDataset('candidate')} type="checkbox" />
          <span><i className="source-dot source-dot--pool" />{t('filters.candidateOnly')}</span>
        </label>
      </fieldset>

      <RangeField
        label={t('filters.gap')}
        unit="eV"
        min={query.gapMin}
        max={query.gapMax}
        onMin={(gapMin) => update({ gapMin })}
        onMax={(gapMax) => update({ gapMax })}
      />
      <RangeField
        label={t('filters.density')}
        unit="g·cm⁻³"
        min={query.densityMin}
        max={query.densityMax}
        onMin={(densityMin) => update({ densityMin })}
        onMax={(densityMax) => update({ densityMax })}
      />
      <RangeField
        label={t('filters.nAtoms')}
        unit="atoms"
        min={query.nAtomsMin}
        max={query.nAtomsMax}
        onMin={(nAtomsMin) => update({ nAtomsMin })}
        onMax={(nAtomsMax) => update({ nAtomsMax })}
      />

      <label className="field">
        <span>{t('filters.spacegroups')}</span>
        <input
          onChange={(event) => update({ spacegroups: event.target.value })}
          placeholder={t('filters.spacegroupsPlaceholder')}
          value={query.spacegroups}
        />
      </label>

      <fieldset className="field-group">
        <legend>{t('filters.crystalSystem')}</legend>
        <div className="chip-grid">
          {CRYSTAL_SYSTEMS.map((value) => (
            <button
              className="filter-chip"
              data-active={query.crystalSystems.includes(value)}
              key={value}
              onClick={() => toggleSystem(value)}
              type="button"
            >
              {t(`system.${value}` as TranslationKey)}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="field-group">
        <legend>{t('filters.family')}</legend>
        <div className="chip-grid">
          {MATERIAL_FAMILIES.map((value) => (
            <button
              className="filter-chip"
              data-active={query.materialFamilies.includes(value)}
              key={value}
              onClick={() => toggleFamily(value)}
              type="button"
            >
              {t(`family.${value}` as TranslationKey)}
            </button>
          ))}
        </div>
      </fieldset>

      <details className="mp-filters">
        <summary><span>{t('filters.more')}</span><ChevronDown size={14} /></summary>
        <div className="mp-filters__body">
          <RangeField
            label={t('filters.nElements')} unit="elements"
            min={query.nElementsMin} max={query.nElementsMax}
            onMin={(nElementsMin) => update({ nElementsMin })}
            onMax={(nElementsMax) => update({ nElementsMax })}
          />
          <RangeField
            label={t('filters.volume')} unit="Å³"
            min={query.volumeMin} max={query.volumeMax}
            onMin={(volumeMin) => update({ volumeMin })}
            onMax={(volumeMax) => update({ volumeMax })}
          />
          <RangeField
            label={t('filters.formationEnergy')} unit="eV/atom"
            min={query.formationEnergyMin} max={query.formationEnergyMax}
            onMin={(formationEnergyMin) => update({ formationEnergyMin })}
            onMax={(formationEnergyMax) => update({ formationEnergyMax })}
          />
          <RangeField
            label={t('filters.hull')} unit="eV/atom"
            min={query.energyAboveHullMin} max={query.energyAboveHullMax}
            onMin={(energyAboveHullMin) => update({ energyAboveHullMin })}
            onMax={(energyAboveHullMax) => update({ energyAboveHullMax })}
          />
          <label className="field">
            <span>{t('filters.stability')}</span>
            <select aria-label={t('filters.stability')} value={query.stability} onChange={(event) => update({ stability: event.target.value as MaterialQuery['stability'] })}>
              <option value="">{t('filters.all')}</option><option value="stable">{t('filters.stable')}</option><option value="unstable">{t('filters.unstable')}</option>
            </select>
          </label>
          <label className="field">
            <span>{t('filters.metallicity')}</span>
            <select aria-label={t('filters.metallicity')} value={query.metallicity} onChange={(event) => update({ metallicity: event.target.value as MaterialQuery['metallicity'] })}>
              <option value="">{t('filters.all')}</option><option value="metal">{t('filters.metal')}</option><option value="nonmetal">{t('filters.nonmetal')}</option>
            </select>
          </label>
          <label className="field">
            <span>{t('filters.magneticOrdering')}</span>
            <input aria-label={t('filters.magneticOrdering')} placeholder="FM, AFM, NM" value={query.magneticOrderings} onChange={(event) => update({ magneticOrderings: event.target.value })} />
          </label>
          <RangeField
            label={t('filters.magnetization')} unit="μB"
            min={query.magnetizationMin} max={query.magnetizationMax}
            onMin={(magnetizationMin) => update({ magnetizationMin })}
            onMax={(magnetizationMax) => update({ magnetizationMax })}
          />
          <RangeField
            label={t('filters.bulkModulus')} unit="GPa"
            min={query.bulkModulusMin} max={query.bulkModulusMax}
            onMin={(bulkModulusMin) => update({ bulkModulusMin })}
            onMax={(bulkModulusMax) => update({ bulkModulusMax })}
          />
          <RangeField
            label={t('filters.shearModulus')} unit="GPa"
            min={query.shearModulusMin} max={query.shearModulusMax}
            onMin={(shearModulusMin) => update({ shearModulusMin })}
            onMax={(shearModulusMax) => update({ shearModulusMax })}
          />
          <fieldset className="field-group availability-filter">
            <legend>{t('filters.availability')}</legend>
            <div className="availability-grid">{PROPERTY_OPTIONS.map((value) => (
              <label key={value}>
                <input type="checkbox" checked={query.hasProperties.includes(value)} onChange={() => toggleProperty(value)} />
                <span>{t(`property.${value}` as TranslationKey)}</span>
              </label>
            ))}</div>
          </fieldset>
        </div>
      </details>
      <p className="filters__note">{t('filters.note')}</p>
      <button aria-label={t('filters.apply')} className="primary-button" type="submit">{t('filters.apply')} <span aria-hidden="true">↗</span></button>
    </form>
  )
}

interface RangeFieldProps {
  label: string
  unit: string
  min?: number
  max?: number
  onMin: (value?: number) => void
  onMax: (value?: number) => void
}

function RangeField({ label, unit, min, max, onMin, onMax }: RangeFieldProps) {
  const { t } = useI18n()
  const number = (value: string) => value === '' ? undefined : Number(value)
  return (
    <fieldset className="field-group range-field">
      <legend>{label} <small>{unit}</small></legend>
      <label><span>{t('range.min')}</span><input type="number" value={min ?? ''} onChange={(event) => onMin(number(event.target.value))} /></label>
      <span className="range-field__line" />
      <label><span>{t('range.max')}</span><input type="number" value={max ?? ''} onChange={(event) => onMax(number(event.target.value))} /></label>
    </fieldset>
  )
}
