# 晶体结构与性质数据库采集说明

**简体中文** · [English](dataset-acquisition.md)

更新时间：2026-07-26

本文件记录 MateriaViva的外部晶体数据库覆盖范围、实际下载状态、许可边界和人工操作。机器可读目录位于 [`scripts/datasets/sources.json`](../scripts/datasets/sources.json)。

来源登记不等于已下载；各来源的状态和许可限制见机器可读目录。

## 1. 存储与格式约定

所有数据库文件，包括 `.part` 断点文件、API 分页、压缩包、收据和后续标准化结果，都只放在：

```text
/path/to/user/SSD/workspace_data/materia-viva/data
```

仓库中的 `data` 是指向上述目录的符号链接。下载器默认保留至少 50 GiB 空闲空间，目标文件先写成 `.part`，完成并检查字节数后再原子改名。大文件的重试由 Python 外层启动新的 curl 进程完成；每个 curl 进程禁用内部重试并从 `.part` 的当前实际字节偏移续传，避免 SSL 中断后内部重试重新打开并截断文件。每个完成的静态文件旁边都有 `*.receipt.json`，记录来源 URL、字节数、SHA-256 和完成时间。

下载层保留各来源的原始格式，这是审计和重建所必需的。原始 JSON、SQL、LMDB、CIF、ASE DB 等不会直接进入网站索引。进入 MateriaViva 前统一执行两层转换：

1. 结构主记录转换为 `Crystal Record v1`，核心字段为 `index, material_id, cif, pbes_gap`。
2. 来源专有性质写入 provenance/property sidecar，再进入统一 SQLite 属性列或 JSON 扩展字段；单位在适配器中转换，原始值、原始单位、来源 ID 和版本始终保留。

因此，“原始归档格式不同”不等于“对外数据库格式不同”。网站和下游程序只读取标准化层，不能直接混读 `data/raw`。

## 2. 数据来源与许可

| 数据库 | 来源与许可说明 |
|---|---|
| [COD](https://wiki.crystallography.net/howtoobtaincod) | CC0；官方也支持 rsync。 |
| ICSD | 商业许可数据；再分发须遵循许可条件。 |
| Materials Project experimental-origin | 另见 MP summary 数据。 |
| AFLOW-ICSD 派生子集 | AFLOW 学术/非商业条款。 |
| [MC3D](https://archive.materialscloud.org/record/2025.139) | 最新档案提供结构及 provenance。 |
| [QMOF](https://github.com/Andrew-S-Rosen/QMOF) | CC BY 4.0。 |
| [CoRE MOF](https://zenodo.org/communities/coremof/) | 版本许可随 Zenodo 记录保存。 |
| [Curated COFs](https://github.com/lipelopesoliveira/curatedCOFs) | 保留仓库版本与来源。 |

## 3. 本轮自动采集的开放数据

| 数据库 | 官方规模/本轮范围 | 状态与方法 |
|---|---|---|
| [Materials Project](https://docs.materialsproject.org/downloading-data/how-do-i-download-the-materials-project-database) | 当前 API 实测 154,377 条 summary | 使用`MP_API_KEY` 环境变量，每 1,000 条一个 gzip 页；包含结构以及 summary 中的能量、稳定性、带隙、磁性、弹性、介电等字段。 |
| [OQMD v1.8](https://oqmd.org/download/) | 21,034,479,961 字节 SQL gzip；2026-02 发布 | 官方整库归档，CC BY 4.0；只保存压缩包，暂不导入，官方估计导入还需约 100 GB。 |
| [AFLOW](https://aflow.org/documentation/) | AFLUX 实测 2,981,853 条 | 两路采集：JARVIS/Figshare 的 400k 属性快照，以及 AFLUX 全量结构+性质分页。后者请求 geometry、fractional positions、species、形成焓、带隙、密度等字段。 |
| [Alexandria](https://alexandria.icams.rub.de/datasets.html) | PBE 3D 约 5M，2D 约 200k，1D 约 100k；另有 PBEsol/SCAN 各约 500k | 镜像官方 2025.07.02 PBE 分片以及 PBE-2D、PBE-1D、PBEsol、SCAN；压缩后约 4.3 GB。 |
| [Alexandria JARVIS repack](https://figshare.com/articles/dataset/27174897) | 同类数据的 2024.10.1 快照 | 同时下载 NIST JARVIS 的 1.4 GB 重打包版本，作为官方分片下载较慢时的完整可用备份；接入时按版本去重。 |
| [GNoME](https://github.com/google-deepmind/materials_discovery/blob/main/DATASET.md) | 约 381k 新稳定结构 | 下载 `by_id.zip`、主性质表和 r2SCAN 表；CC BY-NC 4.0。 |
| [NIST JARVIS-DFT](https://pages.nist.gov/jarvis/databases/) | 2025 版 3D 结构/性质 | 下载 Figshare 最新 2025 JSON ZIP。 |
| [C2DB / 2DHub](https://2dhub.org/) | JARVIS 快照 3,514 条 | 通过 NIST JARVIS 的公开 Figshare 镜像下载；2DHub 还提供在线性质与 API。 |
| [2DMatPedia](https://www.2dmatpedia.org/download) | 约 6k 条 | 官方站当前 TLS/可用性不稳定，使用 NIST JARVIS 的公开 Figshare 镜像。 |
| [OMDB-GAP1](https://omdb.mathub.io/dataset/) | 12,500 个有机晶体 | 官方下载会跳转登录页；同时尝试官方登录入口，并下载 NIST JARVIS/Figshare 公开镜像。 |
| [hMOF](https://figshare.com/articles/dataset/15127758) | 137,651 个假想 MOF | Figshare JSON ZIP。 |
| [SNUMAT](https://figshare.com/articles/dataset/21713885) | 约 10k 条杂化泛函数据 | Figshare JSON ZIP。 |
| [MC2D](https://archive.materialscloud.org/record/2022.84) | 3,077 个抽取结构，2,710 个优化结构 | 已下载抽取结构、优化结构及 `structure_2d.json`，不下载 8.4 GiB AiiDA 全 provenance。 |
| [3DSC](https://github.com/aimat-lab/3DSC) | 3DSC-MP 5,759 条及超导临界温度 | 已下载代码与开放数据；受 ICSD 许可限制的部分只有 ICSD ID，不包含可再分发结构。 |
| [MatterGen data release](https://github.com/microsoft/mattergen) | MP-20 约 45k；Alex-MP-20 约 600k | 下载 Git LFS 中的两个训练集 ZIP。 |
| [MPtrj](https://figshare.com/articles/dataset/23713842) | 约 1.58M 条结构轨迹，12.19 GB | 属于弛豫轨迹数据，不是独特材料结构；已从下载队列排除。 |
| [Matbench Discovery / WBM](https://figshare.com/articles/dataset/Matbench_Discovery_v1_0_0/22715158) | WBM 256,963 个候选结构 | 下载 MP 快照、WBM 初始/弛豫结构、combined entries 与 summary。 |
| [OMat24](https://huggingface.co/datasets/facebook/OMAT24) | 全训练集 100,824,585 个构型 | 属于轨迹/扰动构型数据；排除在独特结构采集与统一入库之外。 |


### 3.2 第二轮扩展来源

机器可读目录现包含 106 个来源。以下项目是第二轮加入的专题结构/性质库：

| 来源 | 规模/内容 | 自动化状态 | 重合处理 |
|---|---|---|---|
| [FAIR-MOFs](https://zenodo.org/records/13254307) | 45,699 个实验 MOF、33,361 个优化 MOF，以及合成条件、孔隙、形成能、拓扑和配体/金属簇 | CC BY 4.0，10 个发布文件已下载并校验 | 与 CoRE/CSD 派生 MOF 做结构匹配，合成条件作为 property/provenance sidecar |
| [MOFX-DB](https://mof.tech.northwestern.edu/databases) | CoREMOF、hMOF、IZA、PCOD-syn、ToBaCCo 的 CIF 和 300 万级吸附数据点 | 六个官方 bulk ZIP 已下载并校验 | CIF 与已有 MOF/zeolite 去重，气体等温线不丢弃 |
| [MOSAEC-DB](https://zenodo.org/records/15808197) | 约 124k 实验 MOF 的化学有效性、描述符和子集 | 5 个开放描述符文件已下载并校验 | 原始 CIF 来自 CSD，需 CSD 许可；不会把开放描述符误当作可再分发结构 |
| [Phonix](https://phonix-db.org/) | 约 20k 目标材料、6,800+ 热导率结果；summary 含结构、声子 DOS 和热输运 | 156 MB Parquet summary 已下载；全 force-constant tar 集远超当前空间边界 | 通过 MP ID 和结构指纹联接 MP，不重复计为新材料 |
| [NovoMag](https://www.novomag.physics.iastate.edu/structure-database) | 3,826 个稀土自由磁性材料及 Fe-Co-Zr 补充结构 | 两个 CC BY 4.0 官方 Zenodo 包已下载并校验 | 保留磁各向异性和磁性来源 |
| [TopoMat](https://www.materialscloud.org/discover/topomat) | 13,628 个结构的能带与拓扑指标，4.02 GB | Materials Cloud bulk tar 已下载并校验 | 结构源自 ICSD/COD；只增加拓扑性质，不增加实验材料计数 |
| [BiDB](https://www.2dhub.org/bidb/bidb.html) / [2D-alloys](https://www.2dhub.org/2dalloys/2dalloys.html) | 8,451 个双层堆垛及 400 个二维合金 | 两个官方 ASE DB 已下载并校验 | 二维单层、双层、异质结和体相使用不同 `structure_role` |
| [SACADA](https://www.sacada.info/) | 当前官方元数据列出 1,661 个已整理的三维碳同素异形体及密度、能隙、相对能、体模量和硬度 | 1,644 个官方 CIF ZIP 已下载；17 个编号在官网没有 ZIP | 缺失项明确记录 unavailable，不将它们误计为已取得结构 |
| [Deem hypothetical zeolites](https://mwdeem.org/PCOD/index.html) | v2.1 `slc/good` 子集含 331k 个 zeolite-like 独特结构 | 三个 CC BY 4.0 bulk 包已下载并校验 | 与 PCOD、IZA、MOFX 中的 zeolite 结构后续统一去重 |
| [ARC-MOF](https://zenodo.org/records/7600474) | 约 280k 个实验或计算 MOF，含 REPEAT 电荷、几何/RAC/RDF 描述符和吸附性质 | CC BY 4.0 的 24 个结构、电荷、描述符和吸附文件已全部下载；4 个 tar.gz 通过压缩流检查 | 先完整保留结构和性质；与 hMOF、CoRE、FAIR-MOF、MOFX 的重合后续再处理 |
| [NIST JARVIS specialized datasets](https://pages.nist.gov/jarvis/databases/) | 1.1k 二维材料、空位/表面/界面、晶态聚合物、MXene、超导和 AGRA/TinNet 催化端点 | 16 个官方 Figshare ZIP 已下载并校验 | 仅采集静态结构端点和对应性质；明确跳过 OCP、ALIGNN-FF、M3GNet-MPF 等重复/力场训练构型 |
| [AMCSD / RRUFF](https://www.rruff.net/about/download-data/) | 矿物 CIF/AMC、衍射记录，以及显微探针、Raman、红外和粉末 XRD 性质 | 16 个结构/性质整库 ZIP 已下载并校验 | 以 AMCSD CIF 为结构本体，RRUFF 光谱/化学/衍射作为同一矿物的多值性质；与 COD 后续匹配 |
| [MPOD](https://mpod.cimav.edu.mx/) | 晶态材料的实验张量性质，采用 CIF/STAR 风格 `.mpod` 文件并链接结构信息 | 已登记；官网支持逐条文件，但本轮未发现稳定 bulk 端点 | 作为实验张量性质 overlay，不把同一 COD 结构重复计数 |
| [EC-MOF Phase-I](https://ec-mof.njit.edu/) | 官方选择器覆盖 1,072 个 bulk/monolayer 候选，论文数据库报告 1,061 个有效结构 | 已取得 1,071 个静态 CIF/性质对；`ZnHTTX_Bulk` 官方结构端点为 404，manifest 显式保留 | bulk 与 monolayer 分开标注；不伪造缺失候选，不下载任何优化轨迹 |
| [AFLOW Prototype Encyclopedia](https://aflowlib.duke.edu/p/index.html) | 2,050 个规范化晶体结构原型，覆盖全部空间群 | Apache-2.0 官方原型定义仓库已下载并校验 | 原型是结构类型参考，不和真实材料条目相加；用于后续 prototype 分类 |
| [QPOD](https://www.2dhub.org/qpod/qpod.html) / [HetDB](https://www.2dhub.org/hetdb/hetdb.html) / [X2DB](https://www.2dhub.org/x2db/x2db.html) | 二维缺陷、异质结和实验二维材料元数据 | 官方浏览/API 可用，但当前文档没有稳定 bulk 文件 | 不抓网页；等待官方 bulk/API 游标导出方案 |
| [PCOD](https://www.crystallography.net/pcod/) | 1,062,771 个公共领域预测 CIF | 官方 rsync 端点已实测可列目录 | 一百万小文件不直接散落到 NTFS；先设计可恢复的 tar/索引流式接入 |
| [MAGNDATA](https://cryst.ehu.es/magndata/) / [IZA](https://www.iza-structure.org/databases/) | 2,000+ 磁结构和已批准 zeolite framework | 官方支持逐条 `.mcif` / CIF，未发现说明清楚的 bulk 端点 | 不做高频网页抓取；IZA 的开放结构+吸附快照由 MOFX-DB 包补充 |
| [Catalysis-Hub](https://www.catalysis-hub.org/) | 表面反应、吸附结构、能量与计算参数 | 官方 GraphQL API 已登记，后续按 publication/dataset 分页导出 | slab、adsorbate、transition state 不与体相晶体合并 |

### 3.3 第三轮扩展来源

第三轮重点检查大规模联邦接口、专题静态结构库以及容易混入轨迹的数据集。采集策略是先保存来源原貌、完整性质和 provenance，统一格式转换及跨库结构去重后置。

| 来源 | 规模/内容 | 当前状态 | 范围说明 |
|---|---:|---|---|
| [ODBX](https://odbx.science/) | 主库 56 条，misc 137,853 条，含形成能和凸包距离 | 137,909 / 137,909 条 OPTIMADE 静态结构已下载，分页 manifest 完整 | 后续与结构预测库去重，保留 ODBX 专有性质 |
| [Materials Cloud OPTIMADE](https://optimade.materialscloud.org/) | 5 个专题库 3,079 条，4 个 Archive 静态库 40,399 条 | 43,478 条已完整下载，使用 provider 默认全字段保留专有性质 | `jk-9v` 的 4,396,695 条 Li-ion 数据主要是 MD 帧，明确排除 |
| [TCOD](https://www.crystallography.net/tcod/) | 7,499 个最终理论 CIF | 官方目录树低频、可恢复下载中 | 只取最终 CIF，不采集计算过程轨迹 |
| [HADB](https://hadb.funmat-ii.se/) | 244 个 hard-coating 条目 | 165 个 DFT/MLIP 静态端点已下载；79 个 AIMD 条目排除 | CIF 与网页性质表、页面哈希一起保留 |
| [CCP-NC Magres](https://www.ccpnc.ac.uk/database/) | 5,804 个最新晶体记录，含 NMR shielding/EFG | PDDL 3,212 条与 CC BY 2,592 条已分块下载并校验 | 每个 immutable record 只保留最新静态 `.magres` 版本 |
| [CMR 静态周期库](https://cmr.fysik.dtu.dk/) | 27 个 ASE DB，覆盖低维、表面、吸附、钙钛矿、OQMD 派生等 | 27 / 27 个周期 ASE SQLite DB 已下载，逐库 `PRAGMA quick_check` 通过；非周期分子、染料、纳米粒子库排除 | C1DB 页面仍在，但官方 `c1db.db` 当前返回 404 |
| [MAD static](https://archive.materialscloud.org/records/c4ene-0mv14) | 95,595 个周期静态结构，含能量及 train/test/val 标签 | train/test/val、子集元数据和原子能已下载并校验 | 不下载 MPtrj benchmark 与大型 AiiDA provenance 归档 |
| [ShiftML2](https://archive.materialscloud.org/records/j2fka-sda13) | 分子晶体训练/测试、实验 NMR benchmark 和 polymorph | 静态部分已下载并校验 | `relax_vs_md.zip` 是轨迹比较包，明确排除 |
| [OBELiX](https://github.com/NRC-Mila/OBELiX) | 599 个已合成固态电解质，321 条带完整 CIF | 全量 CSV 与全 CIF tar 已下载并校验 | 保留实验室温离子电导率、DOI、近似结构标记和 ICSD ID |
| [MOF carbon capture](https://archive.materialscloud.org/record/2018.0016/v3) | 324,426 个假想 MOF，含部分电荷和 CO₂/N₂ 吸附性质 | CC BY 4.0 的 1.2 GiB 结构包、55.5 MiB 性质包及实验结构已下载并通过 tar/ZIP 检查 | 与 hMOF、ARC-MOF、MOFX 等重合后续统一去重 |
| [HEX high-pressure structures](https://springernature.figshare.com/collections/HEX_a_complete_Database_of_High-Pressure_Elemental_Crystal_Structures/7119778/1) | 前 57 个元素在 0、100、200、300 GPa 下的基态和结构搜索候选 | CC0；官方 ZIP 已下载，MD5 匹配并通过 ZIP 检查；排除 macOS 资源叉后有 457 个真实 CIF | 同一元素在不同压力或不同候选结构先分别保留，后续再按结构指纹去重 |
| [HPCSD](https://www.calypso.cn/) | 首发 77,346 个静态高压结构，覆盖 89 种元素 | 门户要求登录，论文说明更多数据需申请；已登记但不抓取认证页面 | 注册并申请 bulk 后仅收集静态结构，不采集结构搜索过程轨迹 |
| [Matterverse](https://optimade.matterverse.ai/) | 实测 31,791,192 个假想材料 | 已验证 OPTIMADE，但每页上限 500、无整库文件；未启动约 63,583 次请求的无边界镜像 | 向提供方申请 bulk snapshot 后再收集 |
| [MOF DB ML](https://mofdb.org/) | H2MOF-ML 4,034 条，hMOF-ML 137,953 条 | 官方 Hugging Face 仓库当前返回 401 | 登录并确认 token/许可后下载；hMOF 与本机副本后续去重 |
| [ADAQ](https://defects.anyterial.se/) | 47,403 个缺陷、79 个 host | 完整或 substantial replication 需提供方许可 | 先联系提供方；不以网页抓取绕过授权边界 |
| [AMDB](https://altermagnets.anyterial.se/) | 180 个 altermagnet 性质记录 | 已登记，结构链接到 MAGNDATA，未发现 bulk | 作为 MAGNDATA 的性质 overlay，不重复计数结构 |
| [NLR MatDB](https://materials.nlr.gov/) | 可再生能源材料的 relaxed structure、稳定性、GW、介电和有效质量 | 支持交互查询/CSV，未发现完整 bulk structure 端点 | 需向 NLR 申请整库导出 |
| [NIMS AtomWork open](https://crystdb.nims.go.jp/en/) | 官方列出 82,000 条开放结构、55,000 条性质、15,000 张相图 | 需要 DICE 注册和 MatNavi 申请；官网明确禁止 scraping | 完成用户注册后使用官方导出，不抓网页 |
| [MatGen](https://matgen.nscc-gz.cn/index_ch.html) | 无机、假想、二维、超导、固态电解质、多孔和 ABACUS 等专题库 | API 文档入口当前 404；需注册或联系 `matgen@nscc-gz.cn` | 申请 bulk/API 后采集静态结构，熔盐 MD 不纳入 |
| [MatCloud+](https://www.matcloud.com.cn/newDataBase/structure) | 多类结构与性质库 | JavaScript 检索页，无公开可再分发 bulk 端点 | 注册后向提供方申请账户级导出 |
| [Atomly](https://atomly.net/) | 官网展示约 349,043 个 compounds | 官方前端写明 API 仅供内部测试和合作者；联系 `atomly@iphy.ac.cn` | 站点证书在 2026-07-26 检查时已过期，不使用不安全自动镜像 |
| [MatCraft](https://matcraft.ai/docs/materials-api/overview) | 文档称 205,000+ 条，主要来源为 MP、AFLOW、JARVIS | guest 100 请求/小时，详情需逐条取结构，条款禁止超限 bulk；API TLS 实测失败 | 这些上游本机已有，申请提供方授权 bulk 后再决定是否镜像 |
| [2D hybrid perovskites](https://arxiv.org/abs/2006.14302) | 515 个实验二维杂化钙钛矿，含 CIF、带隙和预测电荷 | 论文数据库站点仅 HTTP，未发现有明确再分发许可的 bulk 包 | 联系作者取得安全整库包和许可 |
| [OpenMX AB₂ 2D map](https://www.openmx-square.org/2d-ab2/) | 3,844 个 AB₂ 二维候选 | 可交互逐条访问，未发现 bulk archive | 请求 bulk 文件，避免高频逐页抓取 |
| [MPDD](https://providers.optimade.org/index-metadbs/mpdd) | 结构/descriptor 数据库 | registry 的子端点目前仅 HTTP 且不可用 | 联系 Phases Research Lab 获取当前 HTTPS/bulk 地址 |

### 3.4 第四轮静态结构与衍射/电子性质来源

这一轮继续扩大到有机框架、矿物、调制晶体、实验/模拟粉末衍射及超导电子结构。原始包先按来源完整保存，但只有静态结构端点会成为结构记录；衍射、能带、输运等作为性质关联，NEB/迁移路径坐标不转换成晶体记录。目录已增至 106 个来源。

| 来源 | 规模/内容 | 当前状态 | 独特结构边界 |
|---|---:|---|---|
| [HOFSyn](https://figshare.com/articles/dataset/HOFSyn/28856483) | 660 条合成表记录，两个结构包各含 631 个实际 CIF | CSV、原始 CIF 和 P1 标准化 CIF 均已下载并通过 ZIP 检查 | 同一 HOF 的 raw/P1 版本先保留来源关系，后续结构指纹去重；2.35 GB 文献 PDF 包不下载 |
| [Open-framework AlPO](https://figshare.com/articles/dataset/Database_of_Open-Framework_Aluminophosphate_Structures/7822574) | 312 个实验开放骨架磷酸铝，含 topology 和模拟 XRD | 312 个 CIF 与 XLSX 性质表已下载、可完整解压 | 每个发布结构只作为一个静态端点；XRD 是性质，不生成额外结构 |
| [opXRD](https://zenodo.org/records/15298026) | 92,552 个实验粉末图谱；2,179 个带结构标签，其中 912 个完整结构、1,267 个部分标签 | 1.40 GB 官方 ZIP 已下载并通过完整 ZIP 检查；逐条解析计数与发布规模一致 | 只有 912 个含晶格和完整原子 basis 的标签进入结构层；部分标签和其余图谱作为实验性质数据，不产生结构 |
| [SIMPOD](https://doi.org/10.57760/sciencedb.09755) | 467,861 个 COD 静态结构及模拟一维粉末衍射 | 47,781,765,915 字节 `Structures.zip` 已完成，SHA-256 收据和全量 Zip64 CRC 校验通过 | COD 重合暂不删；下载承载结构和一维衍射的主包，排除 29.4 GB 派生图片及两个冗余 CSV 导出；旧版 Info-ZIP 6.00 会误判该超大 Zip64 文件，应使用 Python `zipfile` 校验 |
| [SPSE](https://figshare.com/articles/dataset/High-Throughput_Screening_Platform_for_Solid_Electrolytes_Combining_Hierarchical_Ion-Transport_Prediction_Algorithms_/12011412) | 91,763 条静态结构以及 BVSE/CAVD/电导描述符 | 数据 ZIP 与 README 已下载并校验；实际为 6 个 NDJSON 表 | `cifs.json` 的 91,763 条进入候选结构层；49 条 hierarchical 记录里的 `paths` 坐标数组明确排除，不当作轨迹帧或结构 |
| [SuperBand](https://github.com/ljcj007/SuperBand) | 2,474 个超导体的结构、能带和费米面 | 13.29 GB 官方 HDF5 与代码快照均已完成并校验 | 结构主要源自 MP/OQMD，先保留 SuperBand 专有电子性质，后续按结构联接而不重复计数 |
| [NIMS PhononDB](https://mdr.nims.go.jp/collections/8g84ms862?locale=en) | 10,034 个 MP 静态材料的 harmonic phonon、DOS 和热力学性质 | CC BY 4.0；目前逐条数据集开放但没有 collection-level bulk 文件，已登记申请整包 | 每个 MP ID 只生成一个静态结构记录；`phonopy_params.yaml.xz` 中的 displacement supercells 只作为声子性质输入，不生成额外结构 |
| [B-IncStrDB](https://cryst.ehu.es/bincstrdb/) | 282 个调制或复合晶体，包括 47 个 composite entries | 282 / 282 个官方 msCIF 已下载；29 个索引页、282 份收据及逐文件 SHA‑256 全部校验通过 | 每个数据库 ID 只收一个发布 msCIF；不收 JSmol 图片、动画或任何轨迹 |
| [MinCryst](https://database.iem.ac.ru/mincryst/) / [Webmineral](https://webmineral.com/) | IUCr 目录分别记载 5,000+ mineral phases；Webmineral 有 4,714 个描述条目 | MinCryst 官方主机当前不可达；Webmineral 无明确 bulk 原子坐标导出 | 不抓交互页面；等待提供方恢复或授权 bulk |
| [PowBase](https://www.cristal.org/powbase/index.html) | 169 个 CIF/粉末图谱 ZIP | 官网明确请镜像方联系维护者，故先登记未批量抓取 | 获得镜像许可后再收静态结构/图谱，不从编号序列强行下载 |
| [NIST Crystal Data](https://www.nist.gov/publications/nist-3-nist-crystal-data) / [NIST Surface Structure Database](https://www.nist.gov/publications/nist-42-nist-surface-structure-database-version-30) | 237,671 个晶体记录；近 1,400 个实验表面结构 | 均为 NIST SRD 许可/遗留产品，需要购买或联系 NIST | 取得机构许可后导入最终结构，不绕过许可复制 |

`/path/to/user/SSD/material_data` 的 245 GiB 既有数据已通过 `data/raw/legacy-material-data` 符号链接登记，没有复制。文件级完全重复、MP/OQMD/ICSD/JARVIS 的内容级重合和性质保留规则，以及 OMat24 的排除说明见 [`legacy-ssd-data-inventory.zh-CN.md`](legacy-ssd-data-inventory.zh-CN.md)。

Materials Project 这里的“全量”是当前主 API 的全部材料级 `SummaryDoc`，不是原始 VASP 任务、构建中间对象、图片及所有用户附件的无差别复制。[MP AWS Open Data](https://docs.materialsproject.org/downloading-data/aws-opendata) 的旧版 parsed/build 对象已有约 55.9 GB，结构图片另约 58 GB；这些内容与材料级结构/性质检索大量重复，本轮不下载。MPContribs 还包含按项目独立维护的公开、私有和不同许可数据；官方建议通过 `mpcontribs-client` 按项目调用 `download_contributions()`。本轮单独收集 QMOF 等独特结构项目，明确排除 MPtrj 等轨迹项目，也不会越权下载私有项目或把不同项目附件混为主库数据。

下载命令均可重复运行，已完成文件会跳过，未完成文件从 `.part` 继续：

```bash
cd /path/to/user/workspace/materia-viva

# 查看全部来源
PYTHONPATH=. python scripts/datasets/acquire.py --list

# 静态归档；--source 可以重复
PYTHONPATH=. python scripts/datasets/acquire.py \
  --source oqmd --source alexandria --source gnome

# MP 全量 summary API
MP_API_KEY='你的密钥' PYTHONPATH=. \
  python scripts/datasets/materials_project.py

# AFLOW 全量 AFLUX；10,000 条/页
PYTHONPATH=. python scripts/datasets/aflow.py --page-size 10000

# SACADA 独特碳结构；自动跳过已完成条目和官方缺失的单条 ZIP
PYTHONPATH=. python scripts/datasets/sacada.py --delay 0.25

# EC-MOF 的 bulk/monolayer 结构端点和对应性质
PYTHONPATH=. python scripts/datasets/ec_mof.py --delay 0.25

# 通用 OPTIMADE 静态结构导出，例如 ODBX；每页 gzip、可断点续传
PYTHONPATH=. python scripts/datasets/optimade_export.py --provider odbx-misc

# TCOD 最终 CIF、HADB 静态端点、CCP-NC 最新 Magres
PYTHONPATH=. python scripts/datasets/tcod.py --request-delay 0.02
PYTHONPATH=. python scripts/datasets/hadb.py --request-delay 0.1
PYTHONPATH=. python scripts/datasets/ccpnc_magres.py --chunk-size 250 --request-delay 0.1

# B-IncStrDB：每个 ID 只保存一个发布 msCIF
PYTHONPATH=. python scripts/datasets/bincstrdb.py --request-delay 0.1

# OBELiX 与 MOF carbon-capture 等官方静态 bulk 文件
PYTHONPATH=. python scripts/datasets/acquire.py \
  --source obelix --source mof-carbon-capture --source hex-high-pressure \
  --source hofsyn --source open-framework-aluminophosphate --source spse
```

不要把密钥写进命令历史时，可先在未纳入 Git 的 `.env` 或当前 shell 中设置；脚本只从环境变量读取，收据和 manifest 均不保存密钥。

## 4. 已探测但不做无边界全量镜像

### NOMAD

[NOMAD API](https://nomad-lab.eu/prod/v1/docs/howto/manage/program/download.html) 当前空查询实测返回 19,393,938 个 entry。公开数据通常不需要 token，但每条上传的许可可能不同，且 raw files、archive 与 entry 之间是一对多/多版本关系。将全部原始计算盲目落盘会远超剩余 SSD 容量。

建议先定义子集，例如仅下载包含规范晶体结构、指定程序或指定元素体系的数据；官方 API 可以流式返回 raw ZIP 或 archive：

```bash
curl -X POST 'https://nomad-lab.eu/prod/v1/api/v1/entries/query' \
  -H 'Content-Type: application/json' \
  -d '{"query":{},"pagination":{"page_size":1}}'
```

若需要私有/embargo 数据，再在 NOMAD 用户页面取得 token 并设置 `NOMAD_TOKEN`。公开数据查询不需要该 token。

### OPTIMADE 联邦

[OPTIMADE provider registry](https://providers.optimade.org/providers.json) 当前实测列出 29 个 provider。OPTIMADE 是跨数据库统一查询层，不是一个可以一次性下载的独立数据库；其中不少 provider 已在本表单独采集。后续应以 provider ID + structure ID 保存游标，避免把 MP、OQMD、Alexandria、NOMAD 等重复镜像多次。

### OMat24、MPtrj、Open Catalyst 与其他轨迹库

这些数据主要由同一体系的弛豫、扰动、分子动力学或反应路径中间构型组成，不符合 MateriaViva 当前“独特材料结构 + 对应性质”的采集范围，因此不下载、不转换、不计入统一结构库。旧 SSD 中已存在的 OMat24 全量归档仅保留原文件和 provenance 登记，不参与入库。对于同时提供初始结构和最终弛豫结构的材料数据库，可以保留两个端点并标注 `structure_role`；中间轨迹帧一律排除，端点间是否结构等价留到后续统一指纹去重阶段判断。

### ELEMENTA 与 ELEMENTA Spin

[ELEMENTA](https://huggingface.co/datasets/kairosmaterial/ELEMENTA)（[论文](https://www.kairosmaterials.com/papers/ELEMENTA.pdf)）同样是轨迹数据，但它按“每条弛豫一个终点”提供了明确的轨迹边界和收敛信息，因此按上一段的端点规则接入：只取每条优化轨迹的最后一个 ionic step，中间帧全部丢弃。核心包 38,808,603 帧对应 2,028,008 条弛豫，spin 包 4,713,110 帧对应 207,185 条弛豫，端点合计 2,235,193 个。

轨迹身份是 `(material, structure, spin)` 三元组，不是 `material` 单字段。两个包的标注方式并不一致：核心包和 spin 包开头把磁性状态写进 `material`（`Cl2V_01_spin_00`）并另有 `spin` 字段，而 spin 包后段改为一个组成共用一个 `material`（`Al12Mn4Y4_01`），仅靠 `structure`（`Al12Mn4Y4_01_mag24`）区分，且不再有 `spin` 字段。只按 `material` 分组会把相邻的多条磁性弛豫并成一条，spin 包会因此丢掉约 62% 的轨迹。提取脚本同时以 `ionic_step` 回落作为轨迹边界的兜底判据。

ELEMENTA Spin 对同一几何做多种磁性初始化，这些弛豫终点的 BAWL 指纹相同；去重时按能量取最低的一条作为代表，其余按重复结构合并。ELEMENTA 只标注总能量、受力、应力和磁矩，没有 PBEsol 带隙，因此入库行的 `pbes_gap` 留空。

许可为 CC BY-NC 4.0，比 CC BY 更严格，接入后整个公开快照按非商业条款发布，见 README 的版权和再分发边界。

## 5. 需要用户操作或受许可限制

### MPDS / Pauling File

入口：[MPDS API 文档](https://developer.mpds.io/)；数据浏览与账户：[MPDS](https://mpds.io/)。

MPDS API 需要账户及相应访问权限。使用时应将 API key 保存在本地环境变量中。

### CSD / CCDC

入口：[CSD 许可条件](https://downloads.ccdc.cam.ac.uk/documentation/API/conditions_of_use.html)、[Access Structures](https://www.ccdc.cam.ac.uk/structures/)。

CSD 整库和 CSD Python API 需要有效机构/商业许可，不能在无许可情况下批量下载或再分发。Access Structures 可以按已知 DOI、CCDC deposition number 或 refcode 获取已公开的单条 deposited CIF，但不是不受限整库接口。取得相应许可后可使用 CCDC 官方 API 导出。

### ICSD

入口：[ICSD 官方站](https://icsd.products.fiz-karlsruhe.de/en)、[API 许可条件](https://icsd.products.fiz-karlsruhe.de/sites/default/files/ICSD/documents/terms/ICSD_API_License_2019.pdf)。

ICSD 的批量和 API 使用需要相应授权；离线保存和再分发须遵循许可条件。

### NIMS AtomWork-Adv

入口：[服务与许可](https://atomwork-adv.nims.go.jp/en/service.html)、[购买/申请](https://purchase-atomwork.nims.go.jp/index)。

官方当前列出约 409,723 条结构和 568,195 条性质。72 小时试用只能检索/浏览，不能下载；付费许可通常每年最多下载 5,000 条，整库需联系 NIMS 另行协商。需要你完成 DICE 账户、试用申请和许可购买，或直接向 AtomWork-Adv 咨询整库授权。

### SpringerMaterials、Pearson's Crystal Data、ICDD PDF-4+

- [SpringerMaterials](https://materials.springer.com/)：需要个人或机构订阅；批量/API 权限取决于合同。
- [Pearson's Crystal Data](https://www.crystalimpact.com/pcd/)：商业数据库，需要 Crystal Impact 许可。
- [ICDD PDF-4+](https://www.icdd.com/pdf-4/)：商业粉末衍射数据库，需要 ICDD 许可，不能以网页抓取替代授权导出。

如果学校已有机构许可，需要你先确认许可证是否允许批量导出、离线保存和内部检索；得到明确许可后再接入。

### 第三轮来源所需操作

- [NIMS AtomWork open](https://crystdb.nims.go.jp/en/)：注册 DICE 账户，完成邮箱域名登记并提交 MatNavi usage application。批准后使用页面提供的 TSV/结构导出；官网明确禁止 web scraping。
- [Matterverse](https://optimade.matterverse.ai/)：请联系提供方申请 31,791,192 条结构的 bulk snapshot。公开 OPTIMADE 每页最多 500 条，直接全镜像需要约 63,583 个请求，不应以高频请求替代正式 bulk。
- [MOF DB](https://mofdb.org/)：登录关联的 Hugging Face 账户，确认已接受 H2MOF-ML/hMOF-ML 仓库条件，然后把 token 仅设置在本机环境变量中；不要把 token 写进 Git 或聊天。
- [ADAQ](https://defects.anyterial.se/)：先向站点维护者说明要建立本机研究镜像并申请 substantial replication 许可；当前许可页面只明确允许非实质性摘录。
- [MatGen](https://matgen.nscc-gz.cn/index_ch.html)：注册账户或邮件联系 `matgen@nscc-gz.cn`，申请无机、假想、二维、超导和固态电解质库的 bulk/API；熔盐 MD 库不在本项目范围。
- [Atomly](https://atomly.net/)：邮件联系 `atomly@iphy.ac.cn` 申请合作者 API。官方前端写明 API 当前只供内部测试和合作者使用。
- [MatCloud+](https://www.matcloud.com.cn/newDataBase/structure)：注册后向提供方申请账户级批量导出，并确认各专题库是否允许离线保存和再分发。
- [MatCraft](https://matcraft.ai/docs/materials-api/authentication)：若仍需保存其 MP/AFLOW/JARVIS 聚合记录，先登录生成 API token，再向提供方申请超出常规 rate limit 的 bulk export 授权；条款禁止超限抓取。
- [2D hybrid perovskites](https://arxiv.org/abs/2006.14302)、[OpenMX AB₂](https://www.openmx-square.org/2d-ab2/) 和 [NLR MatDB](https://materials.nlr.gov/)：当前都能交互访问，但未找到安全、许可清楚的整库结构包。建议分别联系作者/维护方索取 bulk 文件，而不是逐页抓取。
- [HPCSD](https://www.calypso.cn/)：注册 CALYPSO/HPCSD 账户并向论文作者或站点维护者申请首发 77,346 条结构的 bulk snapshot；下载后只接入最终静态结构和性质，不接入搜索种群或演化轨迹。
- [PowBase](https://www.cristal.org/powbase/index.html)：官网要求镜像方先联系维护者。镜像这 169 个静态结构/粉末图谱包前应取得许可。
- [MinCryst](https://database.iem.ac.ru/mincryst/) 与 [Webmineral](https://webmineral.com/)：前者当前主机不可达，后者没有明确 bulk 原子坐标导出；需向维护者索取当前静态结构快照和使用条件。
- [NIST Crystal Data](https://www.nist.gov/publications/nist-3-nist-crystal-data) 与 [NIST Surface Structure Database](https://www.nist.gov/publications/nist-42-nist-surface-structure-database-version-30)：确认学校是否有 NIST SRD 许可；无许可时需要向 NIST 购买或申请当前发布包，不能以网页抓取代替。
- [NIMS PhononDB](https://mdr.nims.go.jp/collections/8g84ms862?locale=en)：联系 NIMS MDR 或数据作者申请 10,034 条记录的 collection-level bulk snapshot；当前逐条下载需要约 10,000 个页面和文件请求，不以高频抓取替代整包。取得后只接入每个 MP ID 的静态 unit cell 和声子性质，位移超胞不作为独特结构。

### OMDB、MPOD 与拓扑材料数据库

- [OMDB](https://omdb.mathub.io/dataset/) 的官方 bulk 按钮当前跳转登录；本轮已从 NIST JARVIS/Figshare 镜像取得相同 12.5k 级开放数据。若要官方最新版本，需要注册 OMDB 账户后手工下载。
- [AMCSD / RRUFF](https://www.rruff.net/about/download-data/) 的新下载页已经公开 CIF、AMC、DIF 和各类性质 ZIP，本轮已加入可恢复整库下载，不再需要逐页抓取。
- [MPOD](https://mpod.cimav.edu.mx/) 提供逐条 `.mpod` 张量性质文件，但站点响应较慢且未发现官方 bulk 索引；已记录为后续低频/API 接入项。
- [Topological Materials Database](https://topologicalquantumchemistry.org/) 当前展示约 38,184 个材料，但结构和分类源自 ICSD 等许可数据，未发现可再分发的整库结构下载。可在获得对应 ICSD 权限后按 ID 联接本机 ICSD，而不是抓取网页。

## 6. 完整性检查

静态文件完成后执行：

```bash
find -L data/raw/acquired -type f -name '*.receipt.json' -print
find -L data/raw/acquired -type f -name '*.part' -print
df -h /path/to/user/SSD
```

API 任务以 `manifest.json` 中的 `complete: true`、`downloaded_documents == total_documents` 为完成条件。压缩包随后使用 `gzip -t`、`bzip2 -t`、`unzip -t` 或 `tar -tzf` 做全文件校验；数据库内容通过各来源适配器转换后，再进行结构解析、元素/化学式一致性、单位和重复结构检查。

## 7. 去重与来源优先级

同一结构可能同时出现在 ICSD、COD、MPDS、MP、OQMD、AFLOW、Alexandria、GNoME 和训练集快照中。接入时不按材料名称直接覆盖，采用以下键和规则：

1. 保留 `source`, `source_version`, `source_id`, `license`, `retrieved_at`。
2. 对标准化后的占位、晶格和分数坐标计算结构指纹；先做完全哈希，再做容差结构匹配。
3. 实验结构、计算初始/最终弛豫结构分开标注，不能把计算候选写成实验已合成；轨迹中间构型不采集。
4. 重复结构只合并检索实体，不丢弃来源专有性质；性质保留计算方法、泛函、温压条件和单位。
5. 许可更严格的数据不向许可更宽松的数据集“传染式再分发”；前端只暴露当前授权允许的字段和下载动作。

跨数据库性质挂接——将每个已获取的性质数据库按权威来源 ID 和同一套原胞化 BAWL 指纹匹配到
结构池，指纹未命中者按准入规则收录为新主记录，每个数值保留来源数据库、原始记录号和方法——
由 `scripts/properties/` 实现，详见 [`docs/property-integration.zh-CN.md`](property-integration.zh-CN.md)。
结构不可再分发的来源（SPSE、3DSC-ICSD 等 ICSD 衍生镜像）以仅性质模式运行，绝不贡献结构。
