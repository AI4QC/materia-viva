# 文档冲突：待审清单

[English](doc-conflicts.md) · **简体中文**

更新：2026-08-24

一个量应该只有一个值。这份文件列出**目前还不满足这条的地方**、已经处理掉的部分（不必重做），
以及唯一一件需要"装着完整数据的那台机器"才能定的事。

写这份清单的人无法核实结构池的真实规模：这个 checkout 里 106 个来源的 `data_path` **一个都不存在**，
`data/` 不在 Git 里。所以下面凡是需要观测真值的，一律**只报告、不猜测**。

---

## 一、待审：结构池的规模

### 先说不是问题的部分

**应用本身是对的。** `/api/stats`（[`backend/materials_api/app.py:59`](../backend/materials_api/app.py)）
从 SQLite 的 `metadata` 表读 `experimental_count` / `candidate_count`，这两个键由建索引时写入，
是活值。首页显示的数字因此跟着索引走，不需要人维护。

**错的是散落在脚本里的常量**——它们是同一个事实的手工副本，且停在了 8.2M 时代
（99,162 实验 + 8,125,976 候选 = 8,225,138）。

### 冲突点

| 位置 | 它说 | 严重度 | 后果 |
|---|---|---|---|
| [`scripts/validate_data.py:20`](../scripts/validate_data.py) | `EXPECTED_COUNTS = {"experimental": 99_162, "candidate": 8_125_976}` | **阻断** | `make validate-data` 是 `SystemExit` 硬闸门，计数对不上直接失败，且 Makefile 没传 `--no-count-check` |
| [`scripts/browser_smoke.py:37`](../scripts/browser_smoke.py) | 断言页面上出现字面量 `8,225,138` | **误报失败** | 页面是活的，所以任何计数不等于 8,225,138 的索引都会让这条冒烟测试失败 |
| [`scripts/record_demo.py:165`](../scripts/record_demo.py) | 旁白词"unified and deduplicated into 8,225,138 searchable structures" | **对外可见** | 录出来的演示视频会讲一个过期的数 |
| [`scripts/analysis/plot_dataset_stats.py`](../scripts/analysis/plot_dataset_stats.py) | `6.12M` 共 12 处：1 处 docstring（同处还写 `99k`）+ 11 处图标题与图例 | **对外可见** | 生成的图表标题带过期数字 |
| [`backend/materials_api/indexer.py:1`](../backend/materials_api/indexer.py) | docstring "the experimental and 6.12M structure datasets" | 仅注释 | 不影响行为 |
| [`scripts/datasets/elementa_hash.py:8`](../scripts/datasets/elementa_hash.py)、[`elementa_merge.py:6`](../scripts/datasets/elementa_merge.py) | docstring 提到 "the existing 6.12M pool" | 仅注释 | 论证的是"必须先做 primitive 约化"，不依赖这个数 |

### 需要 zhilong 定的

1. **发布快照的权威计数是多少**——`experimental` 与 `candidate` 各多少条。
   文档侧现在采信的是 2026-08-19 的实测（357,127 / 13,186,150 / 合计 13,543,277，出处
   [`property-integration.zh-CN.md`](property-integration.zh-CN.md)）。这个数是否就是
   `validate_data.py` 该守的数？还是说校验守的是**发布快照**、而那张表数的是**在线索引**，两者本就不同？
   **这个区分决定了是改常量还是改措辞。**

2. **这道闸门要不要继续用字面量。** 建议不要：
   [`validate_data.py:51`](../scripts/validate_data.py) 每次运行都会把真实计数写进
   `data/manifests/<role>.json`。也就是说这个事实**已经有一份权威副本**，常量是第二份手抄。
   若改成与上一份 manifest 比较，闸门守的就变成"数据相对上次校验状态有没有意外变化"——这正是计数闸门
   该守的东西——而更新它变成一次可评审的 manifest diff，而不是改一个常量。

   这只是提议，没有实施。

---

## 二、已解决：文档侧（不必重做）

2026-08-24（提交 `02eeaef`）之前，同一个量在文档里有四个值：

- README 表格与 `property-integration`：357,127 / 13,186,150 / 13,543,277
- `storage-layout` 说同样那两个目录：99,162 / 8,125,976
- README 自己的构建命令：13,077,781（与任何一方都不符）
- `migration-report`：99,162 / 6,120,140，且没说这是历史

依据是 README 自己早就立下的规矩（就在它那张表下方）：

> 计数不写进正文，因为这个项目写死过的每个数字都至少过期过一次；问运行中的实例。

按这条规矩处理后：`storage-layout` 的目录树只说目录装什么、不说装多少；构建命令指向
`validate_data.py` 而不复述数字；README 的表格标注为 2026-08-19 的实测并点明 `GET /api/stats` 才是活数；
`migration-report` 的计数标注为 2026-07-26 当时。

**有测试守着**：`test_no_document_reports_a_pool_size_that_belongs_to_an_earlier_era` 禁止
`13,077,781` / `8,225,138` / `8,125,976` 回到任何正文，`migration-report` 豁免（它是有日期的历史记录）。
另有 `test_the_acquisition_notes_state_the_number_of_sources_the_catalog_holds` 从目录反推来源总数。

---

## 三、不是冲突，但值得知道

**`dataset-acquisition` 的中文版缺内容。** 英文 535 行、中文 337 行，标题数一致（33/33），
所有来源标识符两边都有——差的是英文表格里的若干行摘要（例如 ELEMENTA 那行的
"43,521,713 frames across 2,235,193 relaxations"）。**两边没有数值矛盾**，是完整度差异，
补齐是翻译工作，不是纠错。

**中英文档对之间没有数值矛盾。** 逐对比对过所有带千分位的数字，唯一差异就是上面这条，
以及 `property-integration` 里 `7,836` 中文写成"各 7,836"（同一含义的更紧凑写法）。

---

## 四、怎么复查

```bash
# 文档正文里是否混进了已退役的池规模，以及来源总数是否与目录一致
PYTHONPATH=backend:. python -m pytest backend/tests/test_dataset_acquisition.py -q

# 相对链接是否全部可解析
for f in $(git ls-files "*.md"); do d=$(dirname "$f"); \
  grep -oE '\]\([^)]+\)' "$f" | sed -E 's/^\]\(|\)$//g' | grep -v '^http' | grep -v '^#' | \
  while read -r p; do t="${p%%#*}"; [ -z "$t" ] || [ -e "$d/$t" ] || echo "$f -> $p"; done; done

# 代码里还剩哪些旧时代常量
grep -rn "99_162\|8_125_976\|8,225,138\|6\.12M" $(git ls-files "*.py")
```

活值以运行中的实例为准：

```bash
curl -s http://127.0.0.1:8000/api/stats
```
