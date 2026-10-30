<p align="center">
  <img src="frontend/public/logo.svg" alt="MateriaViva" width="760">
</p>

# MateriaViva

**在线网站：[materia-viva.org](https://materia-viva.org/)**

**简体中文** · [English](README.md)

[![CI](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml/badge.svg)](https://github.com/AI4QC/materia-viva/actions/workflows/ci.yml)
[![Open dataset](https://img.shields.io/badge/Hugging%20Face-MateriaViva--Open-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/datasets/AI4QC/MateriaViva-Open)

MateriaViva 将多个材料数据库中的晶体结构和性质整合为统一、可检索的数据资源。它关联不同来源的记录，同时保留来源标识、性质值、方法和溯源信息。

同一种晶体可能在不同数据库中使用不同的标识，并带有不同的性质数据。MateriaViva 将这些记录关联起来，方便研究者在同一入口检索化学空间、查看结构和比较已有数据。

## 介绍与操作视频

通过完整视频了解 MateriaViva：从材料检索与筛选，到 OVITO 结构检查、性质与谱图比较、来源追溯、CIF 下载和个人工作区使用。

[![MateriaViva 英文介绍与操作视频预览](demo/MateriaViva_demo_preview.gif)](https://github.com/AI4QC/materia-viva/releases/download/tutorials-2026.10.30/MateriaViva-EN.mp4)

上方 GIF 展示网站页面总览及英文成片中的精选操作，点击可打开完整英文视频；也可在下表选择中文版。

| 版本 | 配音与字幕 | 时长 | 完整视频 |
|---|---|---|---|
| English | 英文配音＋英文字幕 | 9 分 11 秒 | [观看／下载 MP4](https://github.com/AI4QC/materia-viva/releases/download/tutorials-2026.10.30/MateriaViva-EN.mp4) |
| 简体中文 | 中文配音＋中文字幕 | 9 分 6 秒 | [观看／下载 MP4](https://github.com/AI4QC/materia-viva/releases/download/tutorials-2026.10.30/MateriaViva-ZH.mp4) |

两版均为 1080p、30 fps，包含 25 个场景，配有真实 OVITO 晶体动画、章节转场和关键操作特写。演示使用原始网页界面及公开目录数据，在本地环境中真实启用 OVITO/Tachyon；线上网站的功能可用状态可能不同。

[字幕、章节表与校验文件](https://github.com/AI4QC/materia-viva/releases/tag/tutorials-2026.10.30) · [视频详情](demo/README.md)

## MateriaViva 提供什么

- **跨库整合。** 使用来源标识和结构指纹匹配不同数据库中的结构记录；性质保留来源、原始标识和计算或测量方法。
- **实验与候选结构。** 界面分别标注两类结构，支持按组成、结构和性质筛选。
- **结构与性质查看。** 通过交互式 3D 浏览结构，比较不同来源的数值，并查看已有曲线和谱。
- **可复用数据。** 公开版提供 Parquet 格式的结构、性质、曲线和预测值，并附来源及许可信息。

## 数据覆盖

以下是项目记录的数据快照。完整结构池与公开版的范围不同，后续版本的数字可能变化；公开版的说明见[数据卡](https://huggingface.co/datasets/AI4QC/MateriaViva-Open)。

| | 完整结构池 | 公开版 |
|---|---:|---:|
| 结构 | 14,590,485 | 10,903,588 |
| 性质值 | 131,824,881 | 113,459,302 |
| 曲线 | 1,198,897 | 850,417 |

完整结构池整合了 **55 个来源数据库**，包括 Materials Project、Alexandria、NOMAD、OQMD 等综合数据库，COD 等实验结构库，以及 QMOF、hMOF、Deem 沸石等专题数据集。详见[来源目录](scripts/datasets/sources.json)和[性质整合说明](docs/property-integration.zh-CN.md)。

这一公开快照还包含 95 个性质任务的预测值。**预测值是模型输出，不是测量结果**；适用范围和评估信息见各任务的元数据。覆盖范围和限制详见[公开数据卡](https://huggingface.co/datasets/AI4QC/MateriaViva-Open)。

## 数据访问与许可

| 数据集 | 访问方式 | 内容 |
|---|---|---|
| [MateriaViva-Open](https://huggingface.co/datasets/AI4QC/MateriaViva-Open) | 公开 | Parquet 格式的结构、性质、曲线和预测值 |
| [MateriaViva](https://huggingface.co/datasets/AI4QC/MateriaViva) | 私有，需要访问权限 | 完整运行索引和开发用切片 |

当开放许可数据库持有某个结构时，该结构可进入公开版。**性质值和曲线沿用各自来源的许可**，可能与结构许可不同；复用前请检查 `licence` 和 `licence_class`。部分记录中，存储的 CIF 来自非开放来源，尽管开放数据库也持有同一结构；如果坐标来源是使用条件的一部分，请检查 `origin_open`。字段和限制详见[数据卡](https://huggingface.co/datasets/AI4QC/MateriaViva-Open)。

完整索引包含 ICSD 等受限数据，需要相应的访问权限和许可。更多信息见[数据采集说明](docs/dataset-acquisition.zh-CN.md)和[来源许可评估](DATA_LICENCES_2026-10-19.zh-CN.md)。

### 下载公开数据

公开版可以独立下载，不需要私有运行索引的访问权限：

```bash
python -m pip install huggingface_hub
hf download AI4QC/MateriaViva-Open --repo-type dataset --local-dir data/open
```

如只需要部分文件，可用 `--include`，例如 `--include "properties/bulk_modulus_vrh.parquet"`。公开版采用 Parquet 格式，不是网页应用使用的运行索引。

## 运行网页应用

需要 Python 3.10+、Node.js 20+ 和 pnpm。下面的示例使用**私有**数据集中的开发切片，Hugging Face 账户需要具有访问权限。

```bash
git clone https://github.com/AI4QC/materia-viva.git
cd materia-viva
python -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt

pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build

hf auth login
python scripts/fetch_index.py slice
python scripts/serve.py --runtime data/slice
```

打开 <http://127.0.0.1:8000>；API 文档位于 <http://127.0.0.1:8000/api/docs>。如需完整索引，可运行 `python scripts/fetch_index.py full`，然后使用 `data/index` 启动服务。两种下载都需要私有数据集的访问权限。

浏览器中的交互式 3D 不需要额外配置。服务端 OVITO 渲染是可选功能，可通过 `MATERIALS_OVITO_PYTHON` 指向安装了 OVITO 的 Python 环境。

## 文档与开发

- [使用指南](docs/user-guide.zh-CN.md) · [数据格式](docs/data-format.zh-CN.md) · [性质整合](docs/property-integration.zh-CN.md)
- [数据来源与采集](docs/dataset-acquisition.zh-CN.md) · [来源许可评估](DATA_LICENCES_2026-10-19.zh-CN.md)
- [贡献指南](CONTRIBUTING.zh-CN.md) · [引用信息](CITATION.cff)

仓库中的 `backend/` 是 FastAPI 后端，`frontend/` 是 React 前端，`scripts/` 包含数据处理脚本，`schemas/` 和 `docs/` 分别保存数据模式和文档。数据文件与运行索引不保存在 Git 中。

## 许可

MateriaViva 代码采用 [CC BY-NC 4.0](LICENSE) 许可。外部来源的数据仍受各自的许可和引用要求约束。
