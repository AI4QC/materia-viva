import { ChevronDown, Filter, RotateCcw, Search } from 'lucide-react'

import type { MaterialQuery } from '../lib/query'

interface AdvancedFiltersProps {
  query: MaterialQuery
  onChange: (query: MaterialQuery) => void
  onApply: () => void
}

const CRYSTAL_SYSTEMS = [
  ['triclinic', '三斜'], ['monoclinic', '单斜'], ['orthorhombic', '正交'],
  ['tetragonal', '四方'], ['trigonal', '三方'], ['hexagonal', '六方'], ['cubic', '立方'],
] as const

const PROPERTY_OPTIONS = [
  ['band_gap', '带隙'], ['density', '密度'], ['spacegroup', '空间群'],
  ['formation_energy', '形成能'], ['energy_above_hull', '凸包能'],
  ['magnetism', '磁性'], ['elasticity', '弹性'],
] as const

export function AdvancedFilters({ query, onChange, onApply }: AdvancedFiltersProps) {
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
  const reset = () => onChange({
    ...query,
    datasets: [], formula: '', gapMin: undefined, gapMax: undefined,
    densityMin: undefined, densityMax: undefined, nAtomsMin: undefined,
    nAtomsMax: undefined, nElementsMin: undefined, nElementsMax: undefined,
    volumeMin: undefined, volumeMax: undefined,
    formationEnergyMin: undefined, formationEnergyMax: undefined,
    energyAboveHullMin: undefined, energyAboveHullMax: undefined,
    stability: '', metallicity: '', magneticOrderings: '',
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
          <span className="eyebrow"><Filter size={13} /> 参数域</span>
          <h2>高级筛选</h2>
        </div>
        <button className="icon-button" type="button" onClick={reset} aria-label="重置高级筛选">
          <RotateCcw size={16} />
        </button>
      </div>

      <label className="field">
        <span>化学式、化学体系或材料 ID</span>
        <div className="input-with-icon">
          <Search size={15} aria-hidden="true" />
          <input
            aria-label="化学式、化学体系或材料 ID"
            onChange={(event) => update({ formula: event.target.value })}
            placeholder="如 LiFePO4 / Fe-O"
            value={query.formula}
          />
        </div>
      </label>

      <fieldset className="field-group">
        <legend>数据来源</legend>
        <label className="check-row">
          <input checked={query.datasets.includes('experimental')} onChange={() => toggleDataset('experimental')} type="checkbox" />
          <span><i className="source-dot source-dot--exp" />仅实验结构</span>
        </label>
        <label className="check-row">
          <input checked={query.datasets.includes('candidate')} onChange={() => toggleDataset('candidate')} type="checkbox" />
          <span><i className="source-dot source-dot--pool" />仅候选结构</span>
        </label>
      </fieldset>

      <RangeField
        label="PBEsol 带隙"
        unit="eV"
        min={query.gapMin}
        max={query.gapMax}
        onMin={(gapMin) => update({ gapMin })}
        onMax={(gapMax) => update({ gapMax })}
      />
      <RangeField
        label="密度"
        unit="g·cm⁻³"
        min={query.densityMin}
        max={query.densityMax}
        onMin={(densityMin) => update({ densityMin })}
        onMax={(densityMax) => update({ densityMax })}
      />
      <RangeField
        label="晶胞原子数"
        unit="atoms"
        min={query.nAtomsMin}
        max={query.nAtomsMax}
        onMin={(nAtomsMin) => update({ nAtomsMin })}
        onMax={(nAtomsMax) => update({ nAtomsMax })}
      />

      <label className="field">
        <span>空间群编号</span>
        <input
          onChange={(event) => update({ spacegroups: event.target.value })}
          placeholder="如 62, 225"
          value={query.spacegroups}
        />
      </label>

      <fieldset className="field-group">
        <legend>晶系</legend>
        <div className="chip-grid">
          {CRYSTAL_SYSTEMS.map(([value, label]) => (
            <button
              className="filter-chip"
              data-active={query.crystalSystems.includes(value)}
              key={value}
              onClick={() => toggleSystem(value)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
      </fieldset>

      <details className="mp-filters">
        <summary><span>更多 MP 属性</span><ChevronDown size={14} /></summary>
        <div className="mp-filters__body">
          <RangeField
            label="元素种类数" unit="elements"
            min={query.nElementsMin} max={query.nElementsMax}
            onMin={(nElementsMin) => update({ nElementsMin })}
            onMax={(nElementsMax) => update({ nElementsMax })}
          />
          <RangeField
            label="晶胞体积" unit="Å³"
            min={query.volumeMin} max={query.volumeMax}
            onMin={(volumeMin) => update({ volumeMin })}
            onMax={(volumeMax) => update({ volumeMax })}
          />
          <RangeField
            label="形成能 / 原子" unit="eV/atom"
            min={query.formationEnergyMin} max={query.formationEnergyMax}
            onMin={(formationEnergyMin) => update({ formationEnergyMin })}
            onMax={(formationEnergyMax) => update({ formationEnergyMax })}
          />
          <RangeField
            label="凸包能" unit="eV/atom"
            min={query.energyAboveHullMin} max={query.energyAboveHullMax}
            onMin={(energyAboveHullMin) => update({ energyAboveHullMin })}
            onMax={(energyAboveHullMax) => update({ energyAboveHullMax })}
          />
          <label className="field">
            <span>稳定性</span>
            <select aria-label="稳定性" value={query.stability} onChange={(event) => update({ stability: event.target.value as MaterialQuery['stability'] })}>
              <option value="">全部</option><option value="stable">稳定</option><option value="unstable">亚稳 / 不稳定</option>
            </select>
          </label>
          <label className="field">
            <span>金属性</span>
            <select aria-label="金属性" value={query.metallicity} onChange={(event) => update({ metallicity: event.target.value as MaterialQuery['metallicity'] })}>
              <option value="">全部</option><option value="metal">金属</option><option value="nonmetal">非金属</option>
            </select>
          </label>
          <label className="field">
            <span>磁序</span>
            <input aria-label="磁序" placeholder="FM, AFM, NM" value={query.magneticOrderings} onChange={(event) => update({ magneticOrderings: event.target.value })} />
          </label>
          <RangeField
            label="总磁矩" unit="μB"
            min={query.magnetizationMin} max={query.magnetizationMax}
            onMin={(magnetizationMin) => update({ magnetizationMin })}
            onMax={(magnetizationMax) => update({ magnetizationMax })}
          />
          <RangeField
            label="体积模量" unit="GPa"
            min={query.bulkModulusMin} max={query.bulkModulusMax}
            onMin={(bulkModulusMin) => update({ bulkModulusMin })}
            onMax={(bulkModulusMax) => update({ bulkModulusMax })}
          />
          <RangeField
            label="剪切模量" unit="GPa"
            min={query.shearModulusMin} max={query.shearModulusMax}
            onMin={(shearModulusMin) => update({ shearModulusMin })}
            onMax={(shearModulusMax) => update({ shearModulusMax })}
          />
          <fieldset className="field-group availability-filter">
            <legend>属性可用性</legend>
            <div className="availability-grid">{PROPERTY_OPTIONS.map(([value, label]) => (
              <label key={value}>
                <input type="checkbox" checked={query.hasProperties.includes(value)} onChange={() => toggleProperty(value)} />
                <span>{label}</span>
              </label>
            ))}</div>
          </fieldset>
        </div>
      </details>
      <p className="filters__note">当前数据源没有提供的属性会保留为空；筛选语义和 API 已就绪，可直接接入后续计算结果。</p>
      <button aria-label="应用筛选" className="primary-button" type="submit">应用筛选 <span aria-hidden="true">↗</span></button>
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
  const number = (value: string) => value === '' ? undefined : Number(value)
  return (
    <fieldset className="field-group range-field">
      <legend>{label} <small>{unit}</small></legend>
      <label><span>最小</span><input type="number" value={min ?? ''} onChange={(event) => onMin(number(event.target.value))} /></label>
      <span className="range-field__line" />
      <label><span>最大</span><input type="number" value={max ?? ''} onChange={(event) => onMax(number(event.target.value))} /></label>
    </fieldset>
  )
}
