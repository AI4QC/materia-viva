# CMU · Crystal Material Universe

[![CI](https://github.com/AI4QC/matdata/actions/workflows/ci.yml/badge.svg)](https://github.com/AI4QC/matdata/actions/workflows/ci.yml)
[![Dataset](https://img.shields.io/badge/Hugging%20Face-AI4QC%2Fmatdata-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AI4QC/matdata)

Crystal Material Universe（CMU）是一个晶体结构数据仓库与可视化检索站点。当前统一
索引包含 99,162 条实验晶体结构和 6,120,140 条候选结构，共 6,219,302 条记录。系统
提供交互式元素周期表、多元素包含/排除组合、Materials Project 风格属性筛选、
OVITO/Tachyon 高质量渲染、浏览器交互式 3D，以及可持久化的日间/夜间主题。

![Crystal Material Universe](demo/CMU_Crystal_Material_Universe_demo_2K60_cover.png)

## 数据获取

本 GitHub 仓库**不包含数据库文件、统一索引、渲染缓存或未完成下载**。完整数据通过
[Hugging Face Dataset：AI4QC/matdata](https://huggingface.co/datasets/AI4QC/matdata)
发布；若页面当前要求登录或授权，请使用有访问权限的 Hugging Face 账户。Git 中只保存
应用代码、数据模式、来源目录、文档、测试和演示资产。

下载数据后，将数据目录挂载或链接为仓库根目录下的 `data`：

```bash
git clone https://github.com/AI4QC/matdata.git
cd matdata

export CMU_DATA_ROOT=/path/on/ssd/cmu-data
ln -s "$CMU_DATA_ROOT" data
```

不要把 `data` 替换成需要提交的普通目录。`.gitignore` 会排除 `data`、`runtime`、原始
归档、索引、`.part`、收据、缓存和本机密钥。

预期的数据目录结构为：

```text
data/
├── sources/
│   ├── experimental/        99,162 条实验结构
│   └── candidate/           6,120,140 条候选结构
├── index/                   SQLite 检索库与压缩 CIF blob
├── manifests/               Crystal Record v1 校验报告
└── raw/                     外部来源原始归档与 provenance
```

本机 SSD 迁移与旧路径兼容关系见
[`docs/storage-layout.md`](docs/storage-layout.md)。

## 统一数据格式

进入 CMU 的结构主记录统一采用 `Crystal Record v1`：

```text
index,material_id,cif,pbes_gap
```

字段顺序、数据类型、非空约束和 split 计数由流式校验器强制执行。完整规范见
[`docs/data-format.md`](docs/data-format.md)，机器可读模式见
[`schemas/crystal-record-v1.schema.json`](schemas/crystal-record-v1.schema.json)。来源专有
性质作为带单位和 provenance 的 sidecar 保留，再映射到统一索引；原始值不会因标准化
而被覆盖。

网站使用 `data/index/materials.sqlite` 与 `data/index/structures.blob`。SQLite 保存检索
字段和压缩块偏移，blob 顺序保存 zlib 压缩的 CIF，构建过程不需要一次性加载全部源 CSV。

## 外部数据库覆盖

机器可读来源目录当前登记 100 个晶体结构/性质来源。状态快照为：

- 57 个已完成或复用既有数据；
- 当前没有未完成的后台下载；
- 18 个仅登记或等待官方批量采集方案；
- 22 个需要账号、提供方授权或付费许可；
- 3 个轨迹数据源按范围排除。

当前采集只接收独特周期结构及其对应性质。同一计算的弛豫、分子动力学、扰动和反应
路径中间帧不进入结构库；不同来源暂时完整保留，后续统一按晶格、占位和坐标指纹去重，
同时保留所有来源的多值性质与 provenance。完整来源、许可、下载状态和人工操作链接见
[`docs/dataset-acquisition.md`](docs/dataset-acquisition.md)，既有 SSD 数据盘点见
[`docs/legacy-ssd-data-inventory.md`](docs/legacy-ssd-data-inventory.md)。

## 仓库结构

```text
matdata/
├── backend/                 FastAPI、SQLite 查询、结构解析和 OVITO 渲染
├── frontend/                React、TypeScript、Vite 和交互式晶体工作台
├── scripts/                 校验、索引、采集、服务和演示录制工具
├── schemas/                 Crystal Record v1 JSON Schema
├── docs/                    数据、迁移、采集和设计文档
├── demo/                    2K60 演示视频与封面
└── data/                    本地数据链接；不受 Git 管理
```

## 安装

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

OVITO 建议安装在独立 Python 环境中，以隔离原生渲染依赖：

```bash
export MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python
```

可复制 [`.env.example`](.env.example) 保存本机路径；`.env` 不进入 Git。未配置 OVITO 时，
浏览器交互式 3D 仍可使用，但服务端 Tachyon 图片渲染不可用。

## 校验与构建索引

流式检查全部 6,219,302 条发布记录：

```bash
make validate-data
```

构建完整索引：

```bash
python scripts/build_index.py
```

开发时可以构建小样本；只有在源数据已单独通过完整校验时才能跳过源扫描：

```bash
python scripts/build_index.py \
  --limit-per-dataset 1000 \
  --skip-source-validation \
  --output /tmp/cmu-sample-index
```

索引先写入 `.building` 临时文件，完成后原子替换，中断不会破坏现有服务索引。

## 启动网站

```bash
make build

MATERIALS_OVITO_PYTHON=/path/to/ovito-enabled/python \
  python scripts/serve.py --host 0.0.0.0 --port 8000
```

- 网站：`http://127.0.0.1:8000`
- API 文档：`http://127.0.0.1:8000/api/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

## 测试

```bash
make test
make build
```

也可分别运行：

```bash
PYTHONPATH=backend:. python -m pytest backend/tests -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

连接真实索引和 OVITO 后，可执行浏览器验收：

```bash
python scripts/browser_smoke.py
```

## 演示视频

- [2K60 MP4](demo/CMU_Crystal_Material_Universe_demo_2K60.mp4)：2560×1440、60 FPS、H.264 High。
- [2K 封面](demo/CMU_Crystal_Material_Universe_demo_2K60_cover.png)。
- `demo/CMU_Crystal_Material_Universe_demo_2K_source.webm`：浏览器源录屏。

重新录制和转码：

```bash
python scripts/record_demo.py
ffmpeg -y -i demo/CMU_Crystal_Material_Universe_demo_2K_source.webm \
  -vf "minterpolate=fps=60:mi_mode=blend" \
  -c:v libx264 -profile:v high -level:v 5.1 -preset slow -crf 13 \
  -pix_fmt yuv420p -movflags +faststart -an \
  demo/CMU_Crystal_Material_Universe_demo_2K60.mp4
```

## 数据许可与贡献

外部数据库保留各自的许可和引用要求。不要因为结构已经标准化或与开放来源匹配，就
重新分发 ICSD、CSD 等受限来源的原始字段。GitHub 仓库当前不声明统一的软件许可证；
在项目维护者正式选择许可证前，默认保留全部代码权利。

开发和数据来源提交规则见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。引用本项目时可使用
[`CITATION.cff`](CITATION.cff)。
