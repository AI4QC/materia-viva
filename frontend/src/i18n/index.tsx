import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Language = 'en' | 'zh'

const LANGUAGE_STORAGE_KEY = 'mv-lang'

/** English is the default so the site reads for an international audience first. */
export function initialLanguage(): Language {
  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
  if (stored === 'en' || stored === 'zh') return stored
  return 'en'
}

const en = {
  'brand.tagline': 'Self-evolving materials database',
  'brand.home': 'MateriaViva home',
  'nav.main': 'Main navigation',
  'nav.elements': 'Element search',
  'nav.catalog': 'Structure catalog',
  'nav.status': 'UNIFIED INDEX ONLINE',
  'theme.toLight': 'Switch to light mode',
  'theme.toDark': 'Switch to dark mode',
  'theme.light': 'Light',
  'theme.dark': 'Dark',
  'lang.switchTo': '切换到中文',
  'lang.label': 'Language',
  'lang.short': '中文',
  'footer.tagline': 'MateriaViva · unified integration, deduplication and search across crystal data sources.',

  'hero.eyebrow': 'Unified crystal universe · 01',
  'hero.titleLead': 'Every crystal dataset in one place,',
  'hero.titleEm': 'discover 8.22 million unique structures.',
  'hero.subtitle':
    'Unified and deduplicated across sources, bringing 99,162 experimentally synthesizable structures and 8,125,976 candidate structures into a single search space.',
  'hero.metricsLabel': 'Dataset scale',
  'metric.experimental': 'Experimental',
  'metric.candidate': 'Candidates',
  'metric.index': 'Deduplicated index',

  'lab.eyebrow': 'Primary filter',
  'lab.title': 'Select a chemical space',
  'legend.include': 'Include',
  'legend.exclude': 'Exclude',
  'legend.unselected': 'Unselected',
  'readout.anyElement': 'Any element',
  'readout.none': 'None',
  'mode.label': 'Element matching mode',
  'mode.all': 'Contains all',
  'mode.any': 'Contains any',
  'mode.exact': 'Exact system',

  'catalog.eyebrow': 'Matched structures',
  'catalog.results': 'results',
  'catalog.sort': 'Sort',
  'sort.materialId': 'Material ID',
  'sort.formula': 'Formula A–Z',
  'sort.gap': 'Band gap high→low',
  'sort.density': 'Density high→low',
  'sort.atoms': 'Atoms few→many',
  'sort.volume': 'Volume small→large',
  'sort.formationEnergy': 'Formation energy low→high',
  'sort.hull': 'Energy above hull low→high',
  'sort.spacegroup': 'Space group number',

  'filters.eyebrow': 'Parameter domain',
  'filters.title': 'Advanced filters',
  'filters.reset': 'Reset advanced filters',
  'filters.formulaLabel': 'Formula, chemical system or material ID',
  'filters.formulaPlaceholder': 'e.g. LiFePO4 / Fe-O',
  'filters.datasets': 'Data source',
  'filters.experimentalOnly': 'Experimental only',
  'filters.candidateOnly': 'Candidates only',
  'filters.gap': 'PBEsol band gap',
  'filters.density': 'Density',
  'filters.nAtoms': 'Atoms per cell',
  'filters.spacegroups': 'Space group number',
  'filters.spacegroupsPlaceholder': 'e.g. 62, 225',
  'filters.crystalSystem': 'Crystal system',
  'filters.more': 'More MP properties',
  'filters.nElements': 'Number of elements',
  'filters.volume': 'Cell volume',
  'filters.formationEnergy': 'Formation energy / atom',
  'filters.hull': 'Energy above hull',
  'filters.stability': 'Stability',
  'filters.metallicity': 'Metallicity',
  'filters.magneticOrdering': 'Magnetic ordering',
  'filters.magnetization': 'Total magnetization',
  'filters.bulkModulus': 'Bulk modulus',
  'filters.shearModulus': 'Shear modulus',
  'filters.availability': 'Property availability',
  'filters.note':
    'Properties the current source does not provide stay empty; the filter semantics and API are ready for later calculations.',
  'filters.apply': 'Apply filters',
  'filters.all': 'All',
  'filters.stable': 'Stable',
  'filters.unstable': 'Metastable / unstable',
  'filters.metal': 'Metal',
  'filters.nonmetal': 'Non-metal',
  'range.min': 'Min',
  'range.max': 'Max',

  'system.triclinic': 'Triclinic',
  'system.monoclinic': 'Monoclinic',
  'system.orthorhombic': 'Orthorhombic',
  'system.tetragonal': 'Tetragonal',
  'system.trigonal': 'Trigonal',
  'system.hexagonal': 'Hexagonal',
  'system.cubic': 'Cubic',

  'property.band_gap': 'Band gap',
  'property.density': 'Density',
  'property.spacegroup': 'Space group',
  'property.formation_energy': 'Formation energy',
  'property.energy_above_hull': 'Energy above hull',
  'property.magnetism': 'Magnetism',
  'property.elasticity': 'Elasticity',

  'results.errorTitle': 'Search connection interrupted',
  'results.retry': 'Try again',
  'results.emptyTitle': 'No structures matched',
  'results.emptyBody': 'Try including fewer elements, or clear one of the numeric ranges.',
  'results.label': 'Material search results',
  'results.pagination': 'Result pagination',
  'results.prev': 'Previous',
  'results.next': 'Next',
  'results.loading': 'Searching the materials space',
  'results.view': 'View',
  'badge.experimental': 'Experimental',
  'badge.candidate': 'Candidate',
  'card.spacegroup': 'Space group',
  'card.atoms': 'Atoms',
  'card.gap': 'Band gap',
  'card.density': 'Density',

  'detail.label': 'Material detail',
  'detail.close': 'Close material detail',
  'detail.loadFailed': 'Could not load material detail',
  'detail.workbenchFailed': 'Structure workbench failed to load',
  'detail.parsing': 'Parsing crystal structure',
  'detail.downloadCif': 'Download CIF',
  'detail.basic': 'Basic properties',
  'detail.spacegroup': 'Space group',
  'detail.crystalSystem': 'Crystal system',
  'detail.gap': 'Band gap',
  'detail.density': 'Density',
  'detail.atoms': 'Atoms',
  'detail.volume': 'Cell volume',
  'detail.lattice': 'Lattice parameters',
  'detail.composition': 'Elemental composition',
  'detail.provenance': 'Data provenance',
  'detail.provenanceNote':
    'The original CIF is stored compressed exactly as the source provided it; index fields can be rebuilt.',

  'viewer.label': 'Crystal structure viewer',
  'viewer.engines': 'Rendering engine',
  'viewer.interactive': 'Interactive 3D',
  'viewer.ovitoLoading': 'OVITO is generating a ray-traced image',
  'viewer.ovitoAlt': 'OVITO crystal structure render of',
  'viewer.ovitoFailed': 'OVITO rendering is unavailable',
  'viewer.ovitoFailedBody': 'You can continue with the in-browser interactive structure view.',
  'viewer.switchInteractive': 'Switch to interactive view',
  'viewer.sceneLoading': 'Loading interactive scene',
  'viewer.webglFailed': 'This browser cannot start WebGL',
  'viewer.webglFailedBody': 'You can still browse the structure with the OVITO render above.',
  'viewer.camera': 'View',
  'viewer.isometric': 'Isometric',
  'viewer.front': 'Front',
  'viewer.top': 'Top',
  'viewer.model': 'Model',
  'viewer.representation': 'Representation',
  'viewer.ballStick': 'Ball and stick',
  'viewer.spacefill': 'Space filling',
  'viewer.cell': 'Cell',
  'viewer.supercell': 'Supercell',
  'viewer.cellEdges': 'Cell edges',
  'viewer.quality': 'Quality',

  'error.searchFailed': 'Search failed',
  'error.requestFailed': 'Request failed',
} as const

export type TranslationKey = keyof typeof en

const zh: Record<TranslationKey, string> = {
  'brand.tagline': '自进化材料数据库',
  'brand.home': 'MateriaViva 首页',
  'nav.main': '主导航',
  'nav.elements': '元素检索',
  'nav.catalog': '结构目录',
  'nav.status': 'UNIFIED INDEX ONLINE',
  'theme.toLight': '切换到日间模式',
  'theme.toDark': '切换到夜间模式',
  'theme.light': '日间',
  'theme.dark': '夜间',
  'lang.switchTo': 'Switch to English',
  'lang.label': '语言',
  'lang.short': 'EN',
  'footer.tagline': 'MateriaViva · 多源晶体数据统一整合、去重与检索。',

  'hero.eyebrow': 'Unified crystal universe · 01',
  'hero.titleLead': '汇聚全部晶体数据集，',
  'hero.titleEm': '发现 822 万种独特结构。',
  'hero.subtitle': '跨数据源统一整合与去重，将 99,162 个实验可合成结构和 8,125,976 个候选结构汇入同一检索空间。',
  'hero.metricsLabel': '数据集规模',
  'metric.experimental': '实验收录',
  'metric.candidate': '候选收录',
  'metric.index': '统一去重索引',

  'lab.eyebrow': '主筛选器',
  'lab.title': '选择化学空间',
  'legend.include': '包含',
  'legend.exclude': '排除',
  'legend.unselected': '未选择',
  'readout.anyElement': '任意元素',
  'readout.none': '无',
  'mode.label': '元素匹配方式',
  'mode.all': '全部包含',
  'mode.any': '包含任一',
  'mode.exact': '精确体系',

  'catalog.eyebrow': '匹配结构',
  'catalog.results': 'results',
  'catalog.sort': '排序',
  'sort.materialId': '材料编号',
  'sort.formula': '化学式 A–Z',
  'sort.gap': '带隙 高→低',
  'sort.density': '密度 高→低',
  'sort.atoms': '原子数 少→多',
  'sort.volume': '体积 小→大',
  'sort.formationEnergy': '形成能 低→高',
  'sort.hull': '凸包能 低→高',
  'sort.spacegroup': '空间群编号',

  'filters.eyebrow': '参数域',
  'filters.title': '高级筛选',
  'filters.reset': '重置高级筛选',
  'filters.formulaLabel': '化学式、化学体系或材料 ID',
  'filters.formulaPlaceholder': '如 LiFePO4 / Fe-O',
  'filters.datasets': '数据来源',
  'filters.experimentalOnly': '仅实验结构',
  'filters.candidateOnly': '仅候选结构',
  'filters.gap': 'PBEsol 带隙',
  'filters.density': '密度',
  'filters.nAtoms': '晶胞原子数',
  'filters.spacegroups': '空间群编号',
  'filters.spacegroupsPlaceholder': '如 62, 225',
  'filters.crystalSystem': '晶系',
  'filters.more': '更多 MP 属性',
  'filters.nElements': '元素种类数',
  'filters.volume': '晶胞体积',
  'filters.formationEnergy': '形成能 / 原子',
  'filters.hull': '凸包能',
  'filters.stability': '稳定性',
  'filters.metallicity': '金属性',
  'filters.magneticOrdering': '磁序',
  'filters.magnetization': '总磁矩',
  'filters.bulkModulus': '体积模量',
  'filters.shearModulus': '剪切模量',
  'filters.availability': '属性可用性',
  'filters.note': '当前数据源没有提供的属性会保留为空；筛选语义和 API 已就绪，可直接接入后续计算结果。',
  'filters.apply': '应用筛选',
  'filters.all': '全部',
  'filters.stable': '稳定',
  'filters.unstable': '亚稳 / 不稳定',
  'filters.metal': '金属',
  'filters.nonmetal': '非金属',
  'range.min': '最小',
  'range.max': '最大',

  'system.triclinic': '三斜',
  'system.monoclinic': '单斜',
  'system.orthorhombic': '正交',
  'system.tetragonal': '四方',
  'system.trigonal': '三方',
  'system.hexagonal': '六方',
  'system.cubic': '立方',

  'property.band_gap': '带隙',
  'property.density': '密度',
  'property.spacegroup': '空间群',
  'property.formation_energy': '形成能',
  'property.energy_above_hull': '凸包能',
  'property.magnetism': '磁性',
  'property.elasticity': '弹性',

  'results.errorTitle': '检索链路中断',
  'results.retry': '重新尝试',
  'results.emptyTitle': '没有命中结构',
  'results.emptyBody': '尝试减少包含元素，或清除一个数值范围。',
  'results.label': '材料检索结果',
  'results.pagination': '检索结果分页',
  'results.prev': '上一页',
  'results.next': '下一页',
  'results.loading': '正在检索材料空间',
  'results.view': '查看',
  'badge.experimental': '实验结构',
  'badge.candidate': '候选结构',
  'card.spacegroup': '空间群',
  'card.atoms': '原子数',
  'card.gap': '带隙',
  'card.density': '密度',

  'detail.label': '材料详情',
  'detail.close': '关闭材料详情',
  'detail.loadFailed': '无法载入材料详情',
  'detail.workbenchFailed': '结构工作台载入失败',
  'detail.parsing': '正在解析晶体结构',
  'detail.downloadCif': '下载 CIF',
  'detail.basic': '基本性质',
  'detail.spacegroup': '空间群',
  'detail.crystalSystem': '晶系',
  'detail.gap': '带隙',
  'detail.density': '密度',
  'detail.atoms': '原子数',
  'detail.volume': '晶胞体积',
  'detail.lattice': '晶格参数',
  'detail.composition': '元素组成',
  'detail.provenance': '数据溯源',
  'detail.provenanceNote': '原始 CIF 按数据集来源原样压缩保存，索引字段可重新构建。',

  'viewer.label': '晶体结构查看器',
  'viewer.engines': '渲染引擎',
  'viewer.interactive': '交互式 3D',
  'viewer.ovitoLoading': 'OVITO 正在生成光线追踪图像',
  'viewer.ovitoAlt': '的 OVITO 晶体结构渲染',
  'viewer.ovitoFailed': 'OVITO 渲染暂不可用',
  'viewer.ovitoFailedBody': '可以继续使用浏览器内的交互式结构视图。',
  'viewer.switchInteractive': '切换到交互视图',
  'viewer.sceneLoading': '载入交互式场景',
  'viewer.webglFailed': '当前浏览器无法启动 WebGL',
  'viewer.webglFailedBody': '仍可使用上方 OVITO 高质量渲染浏览结构。',
  'viewer.camera': '视角',
  'viewer.isometric': '等轴视图',
  'viewer.front': '前视图',
  'viewer.top': '顶视图',
  'viewer.model': '模型',
  'viewer.representation': '结构表示',
  'viewer.ballStick': '球棍',
  'viewer.spacefill': '空间填充',
  'viewer.cell': '晶胞',
  'viewer.supercell': '超晶胞',
  'viewer.cellEdges': '晶胞边界',
  'viewer.quality': '质量',

  'error.searchFailed': '检索失败',
  'error.requestFailed': '请求失败',
}

const TRANSLATIONS: Record<Language, Record<TranslationKey, string>> = { en, zh }

/** Number locale, so results read naturally in whichever language is active. */
export const NUMBER_LOCALE: Record<Language, string> = { en: 'en-US', zh: 'zh-CN' }

interface I18nValue {
  lang: Language
  setLang: (lang: Language) => void
  t: (key: TranslationKey) => string
  locale: string
}

const I18nContext = createContext<I18nValue | null>(null)

export function I18nProvider({ children, initial }: { children: ReactNode; initial?: Language }) {
  const [lang, setLang] = useState<Language>(() => initial ?? initialLanguage())

  useEffect(() => {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, lang)
  }, [lang])

  const value = useMemo<I18nValue>(() => ({
    lang,
    setLang,
    t: (key) => TRANSLATIONS[lang][key] ?? TRANSLATIONS.en[key] ?? key,
    locale: NUMBER_LOCALE[lang],
  }), [lang])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n must be used inside I18nProvider')
  return value
}
