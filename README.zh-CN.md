<p align="center">
  <img src="frontend/public/logo.svg" alt="Materia Viva" width="760">
</p>

# MateriaViva

**简体中文** · [English](README.md)

[![CI](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml/badge.svg)](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml)
[![Dataset](https://img.shields.io/badge/Hugging%20Face-AI4QC%2FMateriaViva-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AI4QC/MateriaViva)

> **材料发现不该从逐个调用数据库 API 和维护多套账户开始。** MateriaViva 用一个 Hugging Face
> 下载入口交付经过统一、去重和许可审查的数据快照。
>
> **MateriaViva 也不会停在一次性数据合集。** 下一阶段将建立可审计的自我进化闭环，持续发现
> 新数据库和新版本并完成准入检查、格式映射与结构去重。自动发现与整合目前正在开发，
> 尚未上线。

## About MateriaViva

### 问题：材料数据很多，但材料仍然难找

晶体结构并不稀缺。真正缺少的是一个可以直接搜索、比较并追溯来源的材料空间。

同一种晶体可能同时出现在多个数据库中，却使用不同的 ID、字段、单位和文件格式。研究者
常常要分别申请账户、调用批量 API、下载归档、清洗数据，再判断哪些记录只是重复结构、
弛豫中间帧或分子动力学轨迹。即使完成这些工作，性质字段也可能和结构脱节，许可边界还要
重新核对。

结果是：数据已经存在，但在真正开始筛选候选材料之前，大量时间先消耗在数据获取和整理上。

### 我们如何解决

MateriaViva先用 Hugging Face 版本快照替代分散的批量 API 与账户
登录，再把晶体数据整理成一个可检索、可追溯的统一入口。研究者从元素周期表开始选择
化学空间，使用 Materials Project 风格的性质条件缩小结果，最后通过浏览器 3D 或
OVITO/Tachyon 检查结构。

| 原来的障碍 | MateriaViva 的处理方式 |
|---|---|
| 每个数据库都有自己的 API、账户和下载流程 | 允许再分发的数据统一发布为 Hugging Face 版本快照 |
| CIF、JSON、SQL、LMDB 和属性表无法直接混用 | 结构进入统一模式，来源性质保留原值、单位和 provenance |
| 同一结构跨库重复，轨迹帧又会放大材料数量 | 只接收独特周期结构端点，统一做结构指纹去重 |
| 实验结构和计算候选容易混在一起 | 两类记录始终分开标注、筛选和统计 |
| 商业数据与开放数据的边界不清楚 | 许可审查先于发布；受限数据不进入公开包 |
| 下载后仍缺少直观检查工具 | 周期表检索、组合筛选、交互式 3D 和高质量离线渲染在同一界面完成 |

当前统一索引包含：

| 实验晶体结构 | 计算候选结构 | 统一检索记录 |
|---:|---:|---:|
| 357,127 | 13,186,150 | 13,543,277 |

结构池之上另有跨数据库性质层：来自 **54 个已整合来源库**、覆盖 **166 种性质**的
**121,620,776 条性质行**，每个数值都保留来源数据库、原始记录号和计算 / 测量方法；
12,812,918 个材料至少携带一条跨库性质，其中 **1,190,447 个结构由两个及以上来源库共同
贡献**——这个重叠正是去重换来的东西。非标量数据——**1,198,897 条已存谱线**（能带、
声子 / 电子 DOS、粉末 XRD、XAS、拉曼、红外、热导）以及全池按需模拟 XRD——存放于并行
曲线存储。空间群覆盖全池 99.996%。MOF、COF、沸石、分子晶体、二维材料、碳同素异形体等
非常规晶体类别均有标注并可筛选。
详见 [`docs/property-integration.zh-CN.md`](docs/property-integration.zh-CN.md)。

以上为快照数字；运行中实例的 `curl -s http://127.0.0.1:8000/api/stats` 才是准数。

### 已整合的数据库

统一结构池目前由以下数据库汇聚而成，全部经过结构指纹（BAWL / entalpic fingerprint）去重后合并：

| 数据库 | 说明 |
|---|---|
| [LeMat-BulkUnique](https://huggingface.co/datasets/LeMaterial/LeMat-BulkUnique) | 4,273,800 条，逐条保留 `immutable_id` 与指纹 |
| [ELEMENTA / ELEMENTA Spin](https://huggingface.co/datasets/kairosmaterial/ELEMENTA) | 2,005,836 条，每条弛豫轨迹只取最终稳定结构 |
| [Materials Project](https://next-gen.materialsproject.org/) | PBE/PBEsol 计算结构与性质 |
| [OQMD](https://oqmd.org/) | 开放量子材料数据库 |
| [JARVIS-DFT](https://jarvis.nist.gov/) | NIST JARVIS 计算结构与描述符 |
| [AFLOW](https://aflow.org/) | 高通量自动流程结构库 |
| [Alexandria](https://alexandria.icams.rub.de/) | PBE / PBEsol 三维、二维、一维结构 |
| [NOMAD](https://nomad-lab.eu/) | 联邦归档中的计算结构 |
| [OMat24](https://huggingface.co/datasets/facebook/OMAT24) | 由其中提取的独特结构端点，中间轨迹帧不入库 |
| Carolina Materials Database | 214,435 条既有结构库 |
| [COD](https://www.crystallography.net/cod/) | 开放晶体学数据库，CC0 |
| [ICSD](https://icsd.products.fiz-karlsruhe.de/) | 需 FIZ Karlsruhe 授权；受限字段不进入公开快照 |

去重与来源优先级规则见
[`docs/dataset-acquisition.zh-CN.md`](docs/dataset-acquisition.zh-CN.md) 第 7 节。ICSD 等受许可限制的来源
按“版权和再分发边界”处理：本机可用于统一检索，受保护的原始文件和字段不随公开快照发布。

[![播放 MateriaViva 2K60 演示视频](demo/MateriaViva_demo_preview.gif)](demo/MateriaViva_demo_2K60.mp4)

<p align="center"><a href="demo/MateriaViva_demo_2K60.mp4">播放完整 2560×1440 · 60 FPS 演示视频</a></p>

## MateriaViva 不只是把文件放在一起

- 实验可合成结构和计算候选结构拥有独立标签，不用候选数量冒充实验覆盖。
- 只把材料的静态周期结构端点纳入结构库。弛豫、扰动、分子动力学和反应路径中间帧不计为
  新材料。
- 去重不等于丢数据。结构合并后仍保留每个来源的原始 ID、版本、性质、单位、许可和
  provenance。
- 原始归档用于审计和重建，网站只读取经过校验的统一索引，不直接混读来源文件。
- 没有明确开放再分发授权的数据不会出现在 Hugging Face 公开版本中。

## 自我进化的材料整合数据库

MateriaViva 的长期目标不是维护一次性的静态合集，而是持续发现新的材料数据库和已有来源的新版本，
完成许可判断、格式映射、结构去重和质量检查后，再发布新的统一快照。

> [!IMPORTANT]
> 自动发现和自动整合功能尚未实现。当前 102 个来源仍由人工发现和审核，再由可恢复的采集
> 脚本接入。README 将待开发能力与当前实现分开描述。

计划中的闭环是：

```text
发现新来源或版本
        ↓
检查许可、访问方式、静态结构范围和轨迹污染
        ↓
生成或推荐采集与字段映射适配器
        ↓
统一格式、单位和 provenance
        ↓
结构指纹去重并合并跨库性质
        ↓
完整性与异常值检查 + 人工批准
        ↓
发布新的 Hugging Face 快照和变更报告
```

失败记录和人工修正会用于改进下一轮来源识别、字段映射和去重策略。这个过程不会绕过账户、
付费许可或再分发限制；无法确认授权的数据默认不公开。

## 一次下载，而不是重复抓取一百个数据库

在发布层，MateriaViva 取消“由每个用户分别调用传统数据库批量 API 或登录来源账户”的使用
方式。索引整理为带版本、哈希、来源清单和许可清单的数据集，发布在：

### [Hugging Face Dataset · AI4QC/MateriaViva](https://huggingface.co/datasets/AI4QC/MateriaViva)（私有）

**该仓库是私有的，不是开放再分发快照。** 它包含完整的工作索引，其中含有再分发受限的来源：
ICSD（FIZ Karlsruhe 按订阅者授权）、以及 CC BY-NC / 学术条款的 ELEMENTA、GNoME 和 AFLOW。
访问按人授予。要做公开快照，必须先剔除这些来源——每一条性质行都记录了 `source_id`，
所以那个过滤只是一个 `WHERE` 子句，但**目前发布的内容尚未应用它**。

**代码在 GitHub，数据在 Hugging Face。** GitHub 仓库只保存代码、数据模式、来源目录、文档、
测试和演示资产，不包含数据库文件、统一索引、渲染缓存或未完成下载。数据集发布两个变体：

| 变体 | 体积 | 用途 |
|---|---:|---|
| `index/` | 约 47 GB | 完整索引，线上服务使用 |
| `slice/` | 数十 MB | 不下载完整数据也能开发网页前端 |

切片**不是随机抽样**，而是贪心集合覆盖：保证每个数据源、每个性质名、每种曲线类型、
每个结构族都至少出现一次。从一千三百万条里随机取一千条，几乎必然漏掉所有稀有性质，
而那恰恰是最可能坏掉的前端面板——见 [`scripts/export_slice.py`](scripts/export_slice.py)。

### 版权和再分发边界

MateriaViva 自身的代码按 [CC BY-NC 4.0](LICENSE) 发布，只允许非商业使用。整合进来的数据
沿用各自来源的条款，且更严格。

- CC0、CC BY、CC BY-SA、CC BY-NC 等明确允许再分发的数据可以进入公开快照，同时保留原作者、
  版本、许可证和引用要求。
- 商业许可、付费订阅、机构许可、账户条款限制以及没有明确再分发授权的数据库不予开源。
- 对受限来源只发布数据库名称、官方链接、公开元数据、来源 ID 和许可状态，不发布受保护的
  结构、性质字段或原始文件。
- 统一格式不会改变原数据的权利归属。未来的自动发现流程同样必须先通过许可门禁。
- 快照包含 CC BY-NC 4.0 的来源（如 ELEMENTA），因此整合结果不得用于商业用途；ShareAlike
  来源如需接入，须单独确认其许可与 NC 条款的兼容性后再决定是否进入公开快照。

## 当前覆盖范围

机器可读目录目前登记 102 个晶体结构或性质来源。“登记”不等于“公开下载完成”：

- 59 个已完成采集或复用本机已有数据；
- 18 个仅登记，或仍在等待合适的官方批量采集方案；
- 22 个需要账户、提供方授权或付费许可，只保留目录信息；
- 3 个轨迹数据源按项目范围排除；
- 当前没有未完成的后台下载。

其中 ELEMENTA 是轨迹数据集，但按“每条弛豫只取终点”的规则接入，中间帧不计入结构库。

完整来源、许可、下载状态和人工操作说明见
[`docs/dataset-acquisition.zh-CN.md`](docs/dataset-acquisition.zh-CN.md)。既有 SSD 数据及重复关系见
[`docs/legacy-ssd-data-inventory.zh-CN.md`](docs/legacy-ssd-data-inventory.zh-CN.md)。

## 获取代码和数据

```bash
git clone https://github.com/AI4QC/materia-viva.git
cd materia-viva
pip install -e backend  # 或：pip install -r requirements.txt

# 小切片——开发前端够用
python scripts/fetch_index.py slice
python scripts/serve.py --runtime data/slice

# 或完整索引（约 47 GB；下载期间需要约两倍空闲空间，
# 因为文件链接到位之前 hub 缓存里还有一份）
python scripts/fetch_index.py full
python scripts/serve.py --runtime data/index
```

然后打开 <http://127.0.0.1:8000>。`--runtime` 接受任何含有 `materials.sqlite`、
`structures.blob` 和 `curves.blob` 的目录，所以在切片和完整索引之间切换只是换一个命令行参数，
不需要重新构建。

如果数据已经在别的盘上，直接链接进来而不必下载：

```bash
export MV_DATA_ROOT=/path/on/ssd/materia-viva-data
ln -s "$MV_DATA_ROOT" data
```

`data` 和兼容入口 `runtime` 均不受 Git 管理。原始归档、SQLite/blob 索引、`.part`、receipt、
渲染缓存和本机密钥也不会进入提交。预期目录为：

```text
data/
├── sources/                 各数据集的结构导出
├── index/                   完整索引：materials.sqlite + structures.blob + curves.blob
├── slice/                   开发切片，同样三个文件
├── manifests/               Crystal Record v1 校验报告
└── raw/                     来源归档与 provenance
```

这里不写具体数量——本项目里每一个写死的数字都至少过期过一次。要看当前值就问运行中的实例：

```bash
curl -s http://127.0.0.1:8000/api/stats
```

本机 SSD 迁移和旧路径兼容关系见 [`docs/storage-layout.zh-CN.md`](docs/storage-layout.zh-CN.md)。

## 统一数据格式

进入 MateriaViva 的结构主记录采用 `Crystal Record v1`：

```text
index,material_id,cif,pbes_gap
```

流式校验器检查字段顺序、数据类型、非空约束和 split 计数。来源专有性质以 sidecar 保留，
随后映射到统一 SQLite 属性列或 JSON 扩展字段。原始值、单位和来源不会被覆盖。

- 格式说明：[`docs/data-format.zh-CN.md`](docs/data-format.zh-CN.md)
- JSON Schema：[`schemas/crystal-record-v1.schema.json`](schemas/crystal-record-v1.schema.json)
- 服务索引：`data/index/materials.sqlite` + `data/index/structures.blob`

SQLite 保存检索字段和压缩块偏移，blob 顺序保存 zlib 压缩的 CIF。索引器以流式方式处理源
CSV，不需要一次加载全部数据。

## 安装与启动

需要 Python 3.10+ 和 Node.js 20+：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

cd frontend
npm ci
cd ..
```

OVITO 建议放在独立 Python 环境中：

```bash
export MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python
```

未配置 OVITO 时，浏览器交互式 3D 仍可使用，服务端 Tachyon 图片渲染不可用。

校验全部 13,077,781 条发布记录并构建索引（性质层随后用 scripts/properties/run_all.py 重建）：

```bash
make validate-data
python scripts/build_index.py
```

开发时可以构建小样本。只有源数据已经单独通过完整校验时，才应跳过源扫描：

```bash
python scripts/build_index.py \
  --limit-per-dataset 1000 \
  --skip-source-validation \
  --output /tmp/cmu-sample-index
```

构建完成后启动网站：

```bash
make build

MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python \
  python scripts/serve.py --host 0.0.0.0 --port 8000
```

- 网站：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/api/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

索引先写入 `.building` 临时文件，完成后原子替换；中断不会破坏当前服务索引。

## 测试

```bash
make test
make build
```

分别运行：

```bash
PYTHONPATH=backend:. python -m pytest backend/tests -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

连接真实索引和 OVITO 后，可以执行浏览器验收：

```bash
python scripts/browser_smoke.py
```

## 仓库结构

```text
materia-viva/
├── backend/                 FastAPI、SQLite 查询、结构解析和 OVITO 渲染
├── frontend/                React、TypeScript、Vite 和交互式晶体工作台
├── scripts/                 校验、索引、采集、服务和演示录制工具
├── schemas/                 Crystal Record v1 JSON Schema
├── docs/                    数据、迁移、采集和设计文档
├── demo/                    2K60 演示视频、动态预览和封面
└── data/                    本地数据链接，不受 Git 管理
```

## 演示视频

- [首页动态预览](demo/MateriaViva_demo_preview.gif)：800×450，点击后播放完整视频。
- [2K60 MP4](demo/MateriaViva_demo_2K60.mp4)：2560×1440、60 FPS、H.264 High。
- [2K 封面](demo/MateriaViva_demo_2K60_cover.png)。
- `demo/MateriaViva_demo_2K_source.webm`：浏览器源录屏。

重新录制和转码：

```bash
python scripts/record_demo.py
ffmpeg -y -i demo/MateriaViva_demo_2K_source.webm \
  -vf "minterpolate=fps=60:mi_mode=blend" \
  -c:v libx264 -profile:v high -level:v 5.1 -preset slow -crf 13 \
  -pix_fmt yuv420p -movflags +faststart -an \
  demo/MateriaViva_demo_2K60.mp4

# 生成 GitHub README 动态预览
ffmpeg -y -ss 1 -i demo/MateriaViva_demo_2K60.mp4 \
  -filter_complex "fps=5,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=72:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" \
  -loop 0 demo/MateriaViva_demo_preview.gif
```

## 许可、贡献和引用

MateriaViva 按 [CC BY-NC 4.0](LICENSE) 发布，只允许非商业使用。外部数据库保留各自的
许可和引用要求。不要因为结构已经标准化或与开放来源匹配，就重新分发 ICSD、CSD 等受限
来源的原始字段。

- 开发与数据来源提交：[`CONTRIBUTING.zh-CN.md`](CONTRIBUTING.zh-CN.md)
- 项目引用：[`CITATION.cff`](CITATION.cff)
