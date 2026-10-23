# 数据来源 license 汇总与开源结构版本

日期 2026-10-19。范围：MateriaViva 池中全部 14,590,485 个结构，以及能持有这些结构的全部数据库（55 个来源 +
池子自带的 LeMat-Bulk、旧本地池 + 从 ODBX 拆出的 CAMD、Wren，共 59 项）。只看结构来源，不看性质。

结论：

- **需要购买的只有 ICSD**（FIZ Karlsruhe 年费订阅）。而且买了也不能放上 HF：条款只允许向第三方提供
  10–20 条记录。
- **开源版本收录 10,903,588 个结构（74.7%）**，已导出为 Parquet，在 `data/open-release/hf/`，已上传到公开仓库 `AI4QC/MateriaViva-Open`（2026-10-23 完成并逐文件校验，见第五部分末尾）。
  2026-10-23 补入这些结构在索引里的**全部性质值（113,459,302 条，148 个性质）和曲线
  （850,417 条）**，不论来自哪个库；每行标注来源库、许可和 `licence_class`。开源版 = 完整版去掉
  只有闭源库持有的结构（这些结构的性质和曲线也随之去掉）。
- 有两条和项目现有记录相反：**NOMAD 实际是统一的 CC BY 4.0**（之前按「每个上传各自定 license」列为受限）；
  **AFLOW 现在没有任何 license 声明**（注册表里的「academic non-commercial terms」找不到出处）。

每个来源的 license 由三个调研 agent 从提供方自己的页面核实（网站条款、figshare/Zenodo/Materials Cloud 记录的
licence 字段、GitHub LICENSE、数据论文的 data availability）。机器可读版本是
`scripts/source_licences.json`，每项都有证据链接和原文引用。

---

## 第一部分：需要购买的数据库

| 数据库 | 付费方式 | 池中持有的结构 | 只有它持有 | 开源版因其他开源库也有而保留 |
|---|---|--:|--:|--:|
| **ICSD** | FIZ Karlsruhe 年度订阅，按机构计费；每个机构授权下载上限 2 万条 | 77,041 | 58,821 | 17,744 |

- ICSD 条款原文：「Information obtained from the database must not be passed on to any third parties or
  unauthorized users.」只允许给工业客户 10 条、教学或发表 20 条。所以 **58,821 个只在 ICSD 的结构无论买不买都进不了公开版本**。
- 不是我们直接来源、但上游是付费库的两个：**CSD**（CCDC，付费；FAIR-MOFs、CoRE MOF、QMOF 的结构源自它）和
  **MPDS**（MC3D、MC2D 的输入结构源自它）。这些下游库都以自己的开放 license 发布结构，做这个开源版本**不需要买**；
  FAIR-MOFs 的风险见第七部分。

## 第二部分：买不到，但需要对方书面许可才能再分发

| 数据库 | 现状 | 只有它持有的结构 |
|---|---|--:|
| AFLOW | 无 license 声明；2014 年前网站写 CC BY 3.0「at no charge only for fair use」，之后撤下 | 503,914 |
| RRUFF | 明确禁止未经书面许可分发 | 117 |
| IZA 沸石库 | 版权保护，只允许私人/研究使用 | 24 |
| AMDB | 单条和少量条目 CC BY-SA；整库复制需联系提供方 | 0 |

无 license 声明（没有授予任何权利，按不可再分发处理）：ODBX 自有部分（law-gnn 1,707 条、odbx_main 56 条）、
Materiae、AMCSD、Webmineral、SACADA、OpenMX 2D AB2、MOFX-DB、EC-MOF、OMDB、HADB、SPSE。
其中 SPSE 的 91,763 个结构有 91,688 个直接取自 ICSD，却标了 CC BY 4.0，且没有 FIZ 许可声明。好在它在池中只做 id 引用，不持有任何结构。

## 第三部分：只允许非商用

| 数据库 | license | 只有它持有的结构 |
|---|---|----:|
| ELEMENTA | CC BY-NC 4.0 | 1,971,815 |
| GNoME | CC BY-NC 4.0 | 535,608 |

两家都不卖商用授权。如果接受整个数据集变成非商用，收录数可从 10,903,588 升到 13,415,019；
更干净的做法是另出一个 NC 子集。

## 第四部分：全部来源的 license 表

「持有」= 该库提供了这个结构、或有同一 BAWL 指纹的条目、或用它自己的 id 收录了它。一个结构可以被多个库持有，
所以各行之和大于总数。「开源版保留 / 被排除」是该库持有的结构在开源版本中的去向。

| 来源 key | 名称 | license | 类别 | 需购买 | 持有结构 | 仅它持有 | 开源版保留 | 被排除 | 依据 |
|---|---|---|---|:-:|--:|--:|--:|--:|---|
| `icsd` | Inorganic Crystal Structure Database | proprietary | 禁止再分发 | **是** | 77,041 | 58,821 | 17,744 | 59,297 | [链接](https://www.fiz-karlsruhe.de/sites/default/files/ICSD/documents/terms/ICSD_AGB_E_2021.pdf) |
| `rruff` | RRUFF | proprietary | 禁止再分发 |  | 829 | 117 | 705 | 124 | [链接](https://web.archive.org/web/20240101143519/https://rruff.info/) |
| `iza-zeolite` | IZA Database of Zeolite Structures | proprietary | 禁止再分发 |  | 213 | 24 | 127 | 86 | [链接](https://www.iza-structure.org/databases/DatabaseCredits.php) |
| `amdb` | Anyterial Altermagnets Database | CC-BY-SA-4.0 (single entries only) | 禁止再分发 |  | 0 | 0 | 0 | 0 | [链接](https://altermagnets.anyterial.se/about#legal) |
| `elementa` | ELEMENTA and ELEMENTA Spin | CC-BY-NC-4.0 | 仅非商用 |  | 2,005,836 | 1,971,815 | 30,230 | 1,975,606 | [链接](https://huggingface.co/datasets/kairosmaterial/ELEMENTA) |
| `gnome` | GNoME | CC-BY-NC-4.0 | 仅非商用 |  | 554,056 | 535,608 | 18,172 | 535,884 | [链接](https://github.com/google-deepmind/materials_discovery#license) |
| `aflow` | AFLOW | unstated | 未声明 |  | 2,244,621 | 503,914 | 1,733,114 | 511,507 | [链接](https://web.archive.org/web/20140307150650/http://aflowlib.org/) |
| `materiae` | Materiae | unstated | 未声明 |  | 14,334 | 433 | 13,881 | 453 | [链接](https://cmpdc.iphy.ac.cn/materiae/) |
| `omdb-organic` | Organic Materials Database | unstated | 未声明 |  | 11,975 | 1,446 | 10,529 | 1,446 | [链接](https://omdb.mathub.io/page/terms) |
| `mofx-db` | MOFX-DB | unstated | 未声明 |  | 10,665 | 9,244 | 1,358 | 9,307 | [链接](https://www.osti.gov/biblio/2311791) |
| `amcsd` | American Mineralogist Crystal Structure Database | unstated | 未声明 |  | 7,790 | 954 | 6,803 | 987 | [链接](https://rruff.geo.arizona.edu/AMS/amcsd.php) |
| `openmx-2d-ab2` | OpenMX AB2 2D structure map | unstated | 未声明 |  | 2,151 | 1,794 | 304 | 1,847 | [链接](https://www.openmx-square.org/2d-ab2/) |
| `odbx` | Open Databases Integration for Materials Design | unstated | 未声明 |  | 1,768 | 1,695 | 69 | 1,699 | [链接](https://odbx.science/) |
| `sacada` | Samara Carbon Allotrope Database | unstated | 未声明 |  | 1,532 | 1,504 | 21 | 1,511 | [链接](https://www.sacada.info/) |
| `ec-mof` | EC-MOF Phase-I | unstated | 未声明 |  | 1,067 | 1,067 | 0 | 1,067 | [链接](https://ec-mof.njit.edu/) |
| `hadb` | Hard-coating Alloys Database | unstated | 未声明 |  | 123 | 105 | 17 | 106 | [链接](https://doi.org/10.1016/j.tsf.2022.139627) |
| `webmineral` | Webmineral | unstated | 未声明 |  | 0 | 0 | 0 | 0 | [链接](https://webmineral.com/) |
| `spse` | Solid-electrolyte screening platform | CC-BY-4.0 (label) | 未声明 |  | 0 | 0 | 0 | 0 | [链接](https://www.nature.com/articles/s41597-020-0474-y) |
| `legacy-local` | Legacy local pool (unique_structs_all, merged before provenance tracking) | unknown | 来源不明 |  | 1,846,340 | 590,272 | 1,252,278 | 594,062 |  |
| `alexandria` | Alexandria Materials Database | CC-BY-4.0 | 开源 |  | 5,895,932 | 1,233,740 | 5,895,932 | 0 | [链接](https://alexandria.icams.rub.de/about.html) |
| `lemat-bulk` | LeMat-Bulk (Entalpic; MP + OQMD + Alexandria) | CC-BY-4.0 | 开源 |  | 4,273,800 | 0 | 4,273,800 | 0 | [链接](https://huggingface.co/datasets/LeMaterial/LeMat-Bulk) |
| `nomad` | NOMAD Repository and Archive | CC-BY-4.0 | 开源 |  | 3,835,327 | 1,047,208 | 3,835,327 | 0 | [链接](https://nomad-lab.eu/nomad-lab/terms.html) |
| `oqmd` | Open Quantum Materials Database | CC-BY-4.0 | 开源 |  | 1,285,892 | 222,416 | 1,285,892 | 0 | [链接](https://oqmd.org/download/) |
| `matbench-discovery` | Matbench Discovery / WBM | CC-BY-4.0 | 开源 |  | 355,228 | 51,384 | 355,228 | 0 | [链接](https://figshare.com/articles/dataset/Matbench_Discovery_v1_0_0/22715158) |
| `mof-carbon-capture` | Hypothetical MOFs for wet flue-gas carbon capture | CC-BY-4.0 | 开源 |  | 287,610 | 286,906 | 287,610 | 0 | [链接](https://archive.materialscloud.org/record/2018.0016/v3) |
| `cod` | Crystallography Open Database | CC0-1.0 | 开源 |  | 265,903 | 227,570 | 265,903 | 0 | [链接](https://www.crystallography.net/cod/) |
| `carolina` | Carolina Materials Database | CC-BY-4.0 | 开源 |  | 210,000 | 43,796 | 210,000 | 0 | [链接](http://www.carolinamatdb.org/terms/) |
| `jarvis-qetb` | NIST JARVIS-QETB tight-binding dataset | CC-BY-4.0 | 开源 |  | 191,606 | 123,385 | 191,606 | 0 | [链接](https://doi.org/10.6084/m9.figshare.15127788) |
| `materials-project` | Materials Project | CC-BY-4.0 | 开源 |  | 168,989 | 2,113 | 168,989 | 0 | [链接](https://legacy.materialsproject.org/terms) |
| `camd` | CAMD 2022 coarse-grained discovery set (Ye, Lei, Aykol, Montoya), via ODBX | CC-BY-4.0 | 开源 |  | 136,205 | 91,382 | 136,205 | 0 | [链接](https://doi.org/10.6084/m9.figshare.19601956.v1) |
| `deem-zeolites` | Deem PCOD hypothetical zeolites v2.1 | CC-BY-4.0 | 开源 |  | 136,008 | 135,984 | 136,008 | 0 | [链接](https://zenodo.org/records/8035241) |
| `hmof` | Hypothetical MOF database (JARVIS figshare re-upload) | CC-BY-4.0 | 开源 |  | 127,498 | 127,489 | 127,498 | 0 | [链接](https://figshare.com/articles/dataset/15127758) |
| `csllm-negatives` | CSLLM non-synthesizable screening set | CC-BY-4.0 | 开源 |  | 94,797 | 0 | 94,797 | 0 | [链接](https://doi.org/10.6084/m9.figshare.29086931) |
| `jarvis-dft` | NIST JARVIS-DFT 3D | CC-BY-4.0 | 开源 |  | 58,423 | 8,322 | 58,423 | 0 | [链接](https://doi.org/10.6084/m9.figshare.6815699) |
| `cmr-static` | DTU Computational Materials Repository | CC-BY-SA-4.0 | 开源 |  | 48,080 | 30,896 | 48,080 | 0 | [链接](https://cmr.fysik.dtu.dk/) |
| `fair-mofs` | FAIR-MOFs | CC-BY-4.0 | 开源 |  | 33,030 | 29,193 | 33,030 | 0 | [链接](https://zenodo.org/records/13254307) |
| `mc3d` | Materials Cloud MC3D | CC-BY-4.0 | 开源 |  | 28,969 | 6,612 | 28,969 | 0 | [链接](https://archive.materialscloud.org/records/szjaf-cfv74) |
| `materials-cloud-archive-static` | Materials Cloud Archive static datasets (zt-z4, 1z-pd, ed-g2, m0-zg) | CC-BY-4.0 | 开源 |  | 22,704 | 1,908 | 22,704 | 0 | [链接](https://api.datacite.org/dois/10.24435/materialscloud:m0-zg) |
| `qmof` | Quantum MOF Database | CC-BY-4.0 | 开源 |  | 18,555 | 12,190 | 18,555 | 0 | [链接](https://github.com/Andrew-S-Rosen/QMOF) |
| `pcod` | Predicted Crystallography Open Database | public-domain | 开源 |  | 12,418 | 12,418 | 12,418 | 0 | [链接](https://www.crystallography.net/pcod/) |
| `snumat` | SNUMAT hybrid-functional database | CC-BY-4.0 | 开源 |  | 11,478 | 1,715 | 11,478 | 0 | [链接](https://figshare.com/articles/dataset/21713885) |
| `phonondb` | NIMS MDR phonon database (phonondb) | CC-BY-4.0 | 开源 |  | 7,449 | 1,678 | 7,449 | 0 | [链接](https://mdr.nims.go.jp/collections/d7aab932-8512-4b9a-b93d-b61f6e5e7019?locale=en) |
| `2dmatpedia` | 2DMatPedia | CC-BY-4.0 | 开源 |  | 6,491 | 3,799 | 6,491 | 0 | [链接](https://doi.org/10.6084/m9.figshare.7699910.v3) |
| `phonix` | Phonix anharmonic phonon database | CC-BY-4.0 | 开源 |  | 5,031 | 1,078 | 5,031 | 0 | [链接](https://phonix-db.org/) |
| `wren` | Wren coordinate-free coarse-graining set (Goodall et al.), via ODBX | MIT | 开源 |  | 4,694 | 4,306 | 4,694 | 0 | [链接](https://doi.org/10.5281/zenodo.6345276) |
| `c2db` | Computational 2D Materials Database | CC-BY-SA-4.0 | 开源 |  | 3,493 | 1,308 | 3,493 | 0 | [链接](https://2dhub.org/) |
| `jarvis-specialized-structures` | NIST JARVIS specialized structure datasets | CC-BY-4.0 | 开源 |  | 3,443 | 266 | 3,443 | 0 | [链接](https://doi.org/10.6084/m9.figshare.6815705) |
| `mc2d` | Materials Cloud MC2D | CC-BY-4.0 | 开源 |  | 3,164 | 1,725 | 3,164 | 0 | [链接](https://archive.materialscloud.org/records/17gf6-84915) |
| `superband` | SuperBand | CC-BY-4.0 | 开源 |  | 3,147 | 5 | 3,147 | 0 | [链接](https://github.com/ljcj007/SuperBand/blob/main/LICENSE.md) |
| `tcod` | Theoretical Crystallography Open Database | CC0-1.0 | 开源 |  | 2,803 | 1,253 | 2,803 | 0 | [链接](https://www.crystallography.net/tcod/) |
| `novomag` | NovoMag magnetic materials database | CC-BY-4.0 | 开源 |  | 2,478 | 1,521 | 2,478 | 0 | [链接](https://zenodo.org/records/17399362) |
| `core-mof` | CoRE MOF 2019 (public ASR/FSR) | CC-BY-4.0 | 开源 |  | 2,361 | 1,452 | 2,361 | 0 | [链接](https://zenodo.org/records/3677685) |
| `bidb` | 2DHub van der Waals Bilayer Database | CC-BY-SA-4.0 | 开源 |  | 1,023 | 16 | 1,023 | 0 | [链接](https://2dhub.org/) |
| `curated-cof` | CURATED-COFs | MIT | 开源 |  | 757 | 756 | 757 | 0 | [链接](https://github.com/danieleongari/CURATED-COFs/blob/master/LICENSE) |
| `aflow-prototypes` | AFLOW Encyclopedia of Crystallographic Prototypes | Apache-2.0 | 开源 |  | 629 | 0 | 629 | 0 | [链接](https://github.com/aflow-org/aflow_prototype_encyclopedia) |
| `hex-high-pressure` | HEX high-pressure elemental crystal structures | CC0-1.0 | 开源 |  | 241 | 31 | 241 | 0 | [链接](https://doi.org/10.6084/m9.figshare.25403968.v1) |
| `open-framework-aluminophosphate` | Open-framework aluminophosphate database | CC-BY-4.0 | 开源 |  | 186 | 121 | 186 | 0 | [链接](https://figshare.com/articles/dataset/Database_of_Open-Framework_Aluminophosphate_Structures/7822574) |
| `3dsc` | 3DSC superconductors | CC-BY-4.0 | 开源 |  | 0 | 0 | 0 | 0 | [链接](https://github.com/aimat-lab/3DSC/blob/main/LICENSE.md) |
| `obelix` | OBELiX | CC-BY-4.0 | 开源 |  | 0 | 0 | 0 | 0 | [链接](https://arxiv.org/abs/2502.14234) |

带 `id` 引用但不持有结构的来源（3DSC、OBELiX、AMDB、SPSE、Webmineral）持有数为 0：它们的条目是
「这是 ICSD 1234」一类引用，不代表我们存的坐标在它们那里。

## 第五部分：开源结构版本

### 规则

只要有一个开源库（可再分发且可商用：CC0 / 公有领域 / CC BY / CC BY-SA / MIT / Apache）持有，就收录；
开源库和闭源库都有的，保留。三种算作「持有」：

- `origin`：该库提供了我们存的这个结构；
- `hash`：该库自己的条目与它 BAWL 指纹相同；
- 用该库**自己的** id 收录（如 LeMat 的 `agm…` 就是 Alexandria 的结构）。

**跨库 id 引用不算**：MP 条目写着「源自 ICSD 1234」，只说明 MP 有这个化合物的弛豫结构，不说明我们存的 ICSD 坐标在 MP 里。
如果放宽到也算这种引用，只多 59,586 个（10,963,174），所以收紧这一条代价很小。

### 结果

| | 结构数 |
|---|--:|
| 全池 | 14,590,485 |
| **开源版收录** | **10,903,588**（74.7%） |
| 其中实验结构 | 290,118（全池 357,127） |
| 其中计算/假想结构 | 10,613,470 |
| 排除 | 3,686,897 |

排除的结构按原始来源：ELEMENTA 1,975,606；旧本地池 594,062；GNoME 535,611；AFLOW 503,933；ICSD 59,194；
MOFX-DB 9,306；其余 9 个来源合计 8,185。

旧本地池（`local_meta_*.tsv` 的 1,846,340 个）合并时没有记录来源。其中 1,252,278 个被某个开源库独立持有，所以收录；
594,062 个查不到任何开源持有者，只能排除。

### 「保留，但存的坐标来自非开源库」的 2,471,566 个

按规则这些都保留，但存的 CIF 不是开源库提供的。数据里用 `origin_open = false` 标出，需要时可以过滤：

| 原始来源 | 个数 |
|---|--:|
| 旧本地池（来源不明） | 1,252,278 |
| AFLOW | 1,146,355 |
| ELEMENTA | 30,230 |
| **ICSD** | **14,629** |
| GNoME | 11,992 |
| OMDB | 10,442 |
| Materiae | 4,318 |
| 其他 6 个 | 1,322 |

其中 ICSD 的 14,629 个是 ICSD 的实验坐标，只是 COD、OQMD、MP 等也有同一指纹的结构。存储的 CIF 已经由
pymatgen 重写，不带 ICSD 文件头。导出时逐条扫描了 `ICSD`/`FIZ`/`CCDC`/`Copyright` 字样，命中的全是误报：
化学式里的子串（`ScCd…`）、MOF CIF 的 `_ccdc_geom_bond_type` 字段名、COD 备注里引用的 CCDC/ICSD 编号，
以及原子标签里的 `(c)`。如果想更稳妥，可以只发 `origin_open = true` 的部分，
或者把这 14,629 个替换成 COD/OQMD 自己的坐标。

### 每行的 license

每行有 `licence` 列：在持有它的开源库里取最宽松的一个（公有领域 > 署名 > 相同方式共享），`licence_from` 记录取自哪个库。
只存在于 CC BY-SA 库（C2DB、CMR、BiDB）的行是 CC BY-SA，下游衍生必须保持 CC BY-SA。
另有 `open_sources`、`open_source_ids`（`库:原生id`，署名用）、`other_sources`（也持有它的非开源库，只作溯源）。

### 文件

```
data/open-release/
  hf/                      ← 上传 HF 用这个目录
    README.md              数据集卡片（英文，数字由脚本从数据读出）
    licences.json          每个来源的 license、证据链接和原文
    data/structures-*.parquet
    properties/<性质>.parquet   每个性质一个文件，每行带来源、许可、licence_class
    curves/<类型>-<格式>-*.parquet   谱、态密度、能带（JSON 或 SVG 原文）
    predictions/            补全预测（scripts/package_predictions.py 写入）
  classify.json            分类统计（含逐来源表）
  export-manifest.json     导出统计（行数、分片、每种 license 行数、CIF 文件头扫描）
  properties-manifest.json / curves-manifest.json   性质、曲线的逐项统计
  provenance.npz           每个结构的持有者位掩码
```

44 个分片，共 4.2 GB（zstd）。校验结果：行数等于分类收录数（10,903,588），`material_id` 无重复；
随机抽 2,000 条 CIF，pymatgen 全部能解析。其中 9 条的原子数与 `n_sites` 不符，都是 Deem 假想沸石：
索引按原胞记录 `n_sites` 和 `formula`，CIF 存的是两倍大的惯用胞。这是索引原有的约定，卡片里已注明。

重建：

```bash
PY=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python
$PY scripts/export_open_structures.py provenance   # ~1 分钟
$PY scripts/export_open_structures.py classify
$PY scripts/export_open_structures.py export       # ~8 分钟
$PY scripts/export_open_structures.py properties   # ~8 分钟
$PY scripts/export_open_structures.py curves       # ~6 分钟
$PY scripts/export_open_structures.py card
```

license 改了只需要改 `scripts/source_licences.json`，再跑 classify → export → card。

### 公开数据集

开源结构数据集发布于 [AI4QC/MateriaViva-Open](https://huggingface.co/datasets/AI4QC/MateriaViva-Open)。数据来源与许可证据见上文及 `scripts/source_licences.json`。

## 第六部分：和现有记录不一致、需要改的地方

1. **NOMAD 不受限。** NOMAD 条款规定上传者一律以 CC BY 4.0 授权，上传者只能选公开或延期公开，不能选 license；
   datamodel 里 license 字段默认 `CC BY 4.0`，只有管理员能改。抽查 2,000 个公开条目：1,995 个 CC BY 4.0，5 个为空。
   受影响的地方：`scripts/make_dataset_card.py` 和 `paper/figure_scripts/make_si_tables.py` 的 `RESTRICTED` 集合、
   SI 来源表的 dagger 标记，以及「5 个受限来源、31.7% 数据」的说法。
2. **AFLOW 的 license 写法没有出处。** 注册表写「academic non-commercial terms」，现在找不到这条；实际情况是没有声明。
   结论不变（不能再分发），但措辞要改成「未声明 license」。
3. **methods.tex 第 12–15 行的说法和数据不符。** 原文：「Sources that may not redistribute structures are marked
   properties-only in code, so no structure of theirs can enter the pool.」这句只对性质流水线里的 ICSD 适配器成立。
   池子本身在建库时就有 73,823 个 ICSD 提供的实验结构（`synth_meta.tsv`，如 `exp-train-0` = `icsd-1`），
   另有 AFLOW 165 万、ELEMENTA 200 万、GNoME 55 万个结构。
4. **私有完整库里有 ICSD 原始结构。** `AI4QC/MateriaViva` 的 `structures.blob` 含上面 73,823 个 ICSD 结构。
   私有仓库本身没问题，但把访问权给 ICSD 授权机构以外的人就违反 FIZ 条款。
5. **`source_defs.license` 大多是占位符**（如「Materials Project terms」「Figshare record licence」）。
   这次没有改线上索引，可以按 `scripts/source_licences.json` 回填。

## 第七部分：来源许可风险

以下来源的再分发许可仍需进一步核实：

- **FAIR-MOFs**，29,193 个只有它持有：实验部分是按 CSD refcode 命名的 CSD 条目，以 CC BY 4.0 发布，但没有写 CCDC 许可。
  这是开源版里风险最高的一项。
- **hMOF**，127,489 个只有它持有：CC BY 4.0 是 JARVIS 转传时标的，原作者的发布没写 license。结构是假想 MOF，没有受限上游。
- **NOMAD**：我们 2026-09-05 的导出没记录逐条 license，靠的是平台条款。
