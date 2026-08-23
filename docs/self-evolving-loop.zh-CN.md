# 自我进化的材料整合数据库：闭环设计

**简体中文**（英文版待补）

更新：2026-08-23

本文件描述 MateriaViva 从"人工发现 + 人工审核 + 可恢复采集脚本"走向"可审计的自我进化闭环"的
目标设计。它是设计文档，不是现状描述。

> [!IMPORTANT]
> 自动发现和自动整合**尚未实现**。当前 106 个来源全部由人工发现和审核，再由
> [`scripts/datasets/acquire.py`](../scripts/datasets/acquire.py) 等可恢复采集脚本接入，其中 54
> 个已整合进索引。下文全部按「计划」阅读，标注「已实现」的除外。
>
> 标注 **（待定）** 的是本文件提出的建议值，不是已经拍下的决定。

## 0. 这份文档补什么

README 里的闭环只有一张七步流程图。缺的不是流程，而是流程之间的判定条件：变更凭什么判定为
"发生了"、失败往哪里去、生成的适配器凭什么算通过、快照对外承诺了什么。这四件事对应第 2-6 节。

设计取向：**每个新增字段、状态和门槛都必须能指到一个真实来源的真实问题**。推导得出的东西不存，
没发生过的失败不建模。

## 1. 闭环总览

README 的线性七步改成带失败出口的形态。`✋` 标记人工闸门。

```text
[1] 探测上游 → 与上次看到的 seen 比对
        │ 不同 → 继续；相同 → 只更新 checked_at，本轮结束
        ↓
[2] ✋ 许可、访问方式、静态结构范围、轨迹污染判定
        │ 授权不明 → rejected(licence-unclear)（默认不发布，见第 6.4 节）
        ↓
[3] 生成或推荐采集与字段映射适配器（草稿）
        │ 门槛未过 → 留在 acquired，草稿不进 adapters/
        ↓
[4] ✋ 适配器评审并注册
        ↓
[5] 统一格式、单位、provenance → 指纹去重 → 合并跨库性质
        ↓
[6] 完整性与异常值检查
        │ 不通过 → quarantined(integrity-failed)
        ↓
[7] ✋ 发布批准 → 新快照 + 变更报告
```

关键差别是人工闸门有三个（[2] [4] [7]），不是 README 图里末尾唯一一个。许可判定和适配器评审都在
数据进入索引之前——事后批准挡不住已经污染的映射。

## 2. 来源状态与失败出口

### 2.1 状态

```
registered → acquired → integrated
```

任意一步可跳出到两个带原因码的态：

- `rejected(reason)`——判定为不接入，人工可复议，不自动重试；
- `quarantined(reason)`——本轮失败，下一轮重新进入。

不设 `acquiring`（采集脚本本身可恢复，不需要持久化在途状态）、不设 `licence-cleared`（许可判定的
结果是许可字段上的一个布尔，不是来源状态）、不设 `superseded`（上游是否落后，比对 `seen` 即得）。

也**不设 `adapter-pending`**：回填 106 条时发现没有一条能落进 `acquired` 而不同时落进
`adapter-pending`——文件到手而尚无适配器，就是 `acquired` 的全部含义。缺不缺适配器由
`scripts/properties/adapters/` 里有没有对应模块回答，不需要第二个状态。同理，`integrated` 不是一句
自称：它的定义就是"存在适配器模块"，并由测试钉住（`test_integrated_state_matches_the_sources_that_have_an_adapter`）。

**发布可见性不入目录。** 它由许可判定推导：受限来源的 `source_id` 进一条发布拒绝名单，公开快照按
`source_id` 过滤。存一个 `visibility` 字段等于给许可造第二个真相源，两者迟早漂移。

ICSD 是"整合成功 + 不可发布"的标准形态：`state` 为 `integrated`，`access` 为 `licensed`，不出现
在公开快照里。这不是失败态。

### 2.2 原因码

每个码都对应 `sources.json` 里已经存在的真实情形：

| 原因码 | 含义 | 现有实例 |
|---|---|---|
| `licence-unclear` | 再分发授权无法确认 | 默认拒绝出口 |
| `licence-restricted` | 明确受限（付费 / 订阅 / 机构授权） | ICSD、CSD、MPDS |
| `account-required` | 需人工注册或登录，无法自动化 | MatCloud、MatCraft |
| `no-bulk-interface` | 无官方批量接口且禁止爬取 | NOMAD、OPTIMADE 联邦 |
| `scope-trajectory` | 轨迹 / 中间帧数据集，超出静态结构范围 | MPtrj、OMat24 |
| `join-key-missing` | 抓取缺少关联键，数据无法挂接 | Catalysis-Hub |
| `integrity-failed` | 校验和、计数或异常值检查未通过 | 见采集文档第 6 节 |

新码只在真的出现新失败形态时增加，不预先铺开。

**5 条来源现有词表装不下，`state` 留空待决**（第 3 步回填时暴露的）：

| 来源 | status | 缺的是什么 |
|---|---|---|
| `nomad` | `too-large-for-full-mirror` | 有批量接口，是我们主动不做全量镜像——不是 `no-bulk-interface` |
| `optimade` | `registry-downloaded-verified-...-provider-data-is-federated` | registry 已采到并校验，只有联邦的 provider 数据不镜像，一半成功一半不做 |
| `perovskite-database` | `nomad-query-access-cataloged` | 经 NOMAD 查询访问，只登记 |
| `open-materials-db` | `...zero-provider-properties-primary-source-is-cod-not-ingested` | 主来源 COD 已整合，本身冗余 |
| `topological-materials` | `browser-access-no-redistributable-bulk-structures` | 同时是"只有浏览接口"和"不可再分发"，哪个是约束条件 |

前四条大致指向同一个缺口：**"探测过、但主动不做无边界镜像"**（正是
[`docs/dataset-acquisition.zh-CN.md`](dataset-acquisition.zh-CN.md) 第 4 节那一类）。加不加一个
`scope-unbounded` 码，是需要拍的决定，不是能推出来的规则。

### 2.3 与 `status` 文本的关系

状态目前事实上写在 `sources.json` 的 `status` 自由文本里，例如：

```
downloaded-158304-reactions-2026-08-18-excluded-from-ingestion-crawl-omitted-reactionSystems-join-key-so-91-percent-unattachable
```

它同时编码了状态、日期、计数和失败原因，对人有用，应当保留。**`status` 是人读的叙述，新字段是
机器读的状态**，两者并存，不互相替代（不可替代的硬原因见第 3.3 节）。

### 2.4 Catalysis-Hub 走一遍

```
registered → acquired(158304 reactions, 2026-08-18) → rejected(join-key-missing)
```

抓取遗漏了 `reactionSystems` 关联键，91% 的反应挂不到结构上。失败发生在 [4] 之前，索引没有被
污染——这正是把适配器闸门放在入库前的理由。复议路径是重抓一次带关联键的数据，而不是修适配器。

## 3. 变更检测所需的目录字段

### 3.1 现状

`scripts/datasets/sources.json`（`schema_version: 1`）的 106 条记录只有
`id / name / access / official_url / license / data_path / status / downloads`，另有少量条目带
`notes / estimated_documents / paper_url / revision`。带 `revision` 的只有 1 条——ELEMENTA，值是
Hugging Face 提交 SHA `9de9010715da4f563326f99bf3f7ee829cf4486a`。

"上游版本"这个概念在目录里只有这一个个例，其余全被压进 `status` 文本，没有可比较的基线，
"发现新版本"就无从判定。反过来，[`docs/dataset-acquisition.md`](dataset-acquisition.md) 第 7 节
已经承诺"保留 `source`、`source_version`、`source_id`、`license`、`retrieved_at`"——意图早就写下
了，只是目录 schema 里没有落地。

### 3.2 目录不存上游状态（第 1 步跑完后的结论）

这一节原本设计了一个 `upstream` 块（`probe` / `probe_kind` / `seen` / `checked_at`）写进
`sources.json`。第 1 步的探测器跑过全量之后，这个设计被自己的输出否掉了。判据是：**这个值是人工
知识，还是每次运行都能重算的结果？**

- `seen` 全部派生。`data/probe/seen.json` 里 29 个非空 token 全是机器读出来的校验值：HTTP ETag、
  `Last-Modified`、git SHA、HF repo sha、Invenio record id。没有一个需要人。
- `probe` 和 `probe_kind` 也是派生的。`plan_probe()` 是 `downloads[].url` 的纯函数，对全部 106 条
  给出 kind 和端点，零人工输入。原先写"`probe_kind` 决定怎么探测，无法推导"——这句是错的。
- **目录里已经存了版本指针**：它就在下载 URL 里。`arc-mof` / `carolina` / `core-mof` / `topomat`
  这四个"上游已领先"的判定，正是把 URL 里的 record id 与上游最新版比出来的。再存一个
  `upstream.seen` 就是同一个指针存两份——和 §2.1 拒绝 `visibility` 的理由完全相同，而且这四条 URL
  已经在漂移了。
- 变更检测不需要目录字段。`diff_against()` 拿上一轮的旁路文件比即可，第 1 步的验收标准本来就是
  "连跑两次，第二次报未变更"。若把状态写进目录，只读探测器就得变成每轮对版本库里 106 条记录写
  diff 的目录改写器。
- ELEMENTA 顶层的 `revision` 印证的是冗余而非先例：探测器独立推导出了逐字符相同的 sha。它也没有
  任何读者（`scripts/` 与 `backend/` 里 grep 不到），保持原样不动。

**所以：探测状态永久留在旁路文件 `<data root>/probe/seen.json`，不进版本库，目录不加
`upstream` 块，探测器也不提供把结果写回目录的 `--sync`——那只是同一个设计换个名字。**

这个选择的代价必须说清：旁路文件在 `data/` 下，而 `data/` 不进版本库，所以**基线是机器本地的**。
新克隆的仓库、CI、换一台机器都没有基线，所有来源首轮都报 `first-seen`，必须在本机跑过两次才能
回答"变了没变"；SSD 丢了基线跟着丢；两个人也无法共享探测结果。

缓和的一面：**最有价值的那个信号不依赖基线。** `catalog_points_at_older_record` 比的是下载 URL
里的 record id 与上游最新版，所以首轮全是 `first-seen` 时，`arc-mof` / `carolina` / `core-mof` /
`topomat` 这四个发现照样被报了出来。基线丢失只削弱 `http-head` / `hf-revision` / `git-commit`
三类的 `changed` 判定，不会让探测器变哑。真到了需要跨机器共享基线的那天，再讨论把 `seen.json`
纳入版本库——那是一个独立决定，不是现在这个。

目录只该存**无法从 URL 推导的人工知识**，目前只有两项，都还没到：

- `state` / `reason`（第 2.1、2.2 节）——第 3 步，其中 21 条需要人工判断；
- figshare article id（第 3.3 节）——第 4 步，14 条人工补录。

`schema_version` 的跳升因此不属于第 2 步，而是跟着第 3 步真正加字段的那个提交走：现在是 **2**，
新增的是可选的 `state` / `reason` 对，version 1 的旧文件照样加载（每条没有 `state` 的记录读作
`registered`）。

不加的字段及理由（原样保留，均已被数据印证）：

- `check_interval_days`——先用一个全局默认间隔（**待定**），`manual` 即不探测；
- `probe_failures` / 退避计数——探测失败的正确处理是"这次什么也没学到"，下轮自然重试；
- `visibility`——推导得出，见第 2.1 节；
- `etag` / `last_modified` / `content_hash` / `upstream_version` 四个并列字段——同一语义的四种
  编码，只用一个不透明 token。

### 3.3 自动探测的覆盖上限

106 个来源里只有 **45 个带 `downloads[].url`**，其余 61 个（仅浏览接口、逐条下载、需注册、联邦
查询）没有可探测的固定端点，`probe_kind` 永远是 `manual`。**自动变更检测最多覆盖 42% 的目录**，
剩下的靠人工到期复核。这个上限是来源本身的性质，不是实现不足，文档和对外说明都不应暗示 106 个
来源全自动。

> 下表说的是**上游入口**——那 106 个被整合的数据库自己把批量文件托管在哪里，与 MateriaViva
> 自己发布快照的 Hugging Face 仓库（`AI4QC/MateriaViva`，出口）无关。表里的 `huggingface.co`
> 指的是别人的 HF 数据集（`kairosmaterial/ELEMENTA`、`phonix-db/phonix-summary`、
> `colabfit/Carolina_Materials`），不是我们的仓库。

45 个可探测来源按下载 host 分布，以及上游标识能否从现有 URL 直接得到：

| host | 来源数 | 现有 URL 里的上游标识 |
|---|---:|---|
| `ndownloader.figshare.com` | 14 | ❌ 只有文件 id（`files/25453265`），发新版本时不变 |
| `zenodo.org` | 8 | ✅ `api/records/<record_id>/...` |
| `archive.materialscloud.org` | 5 | ✅ `api/records/<record_id>/...` |
| `huggingface.co` | 3 | ✅ `datasets/<repo>/resolve/main/...` |
| github（raw / media / codeload / archive） | 5 | ✅ `<org>/<repo>/<branch>/...` |
| 其余单点 host | 10 | 逐个看，多数只能 `http-head` |

两条直接结论：

- **31 个来源的上游标识已在现有 URL 里**（invenio-latest 13、http-head 11、git-commit 5、
  hf-revision 2），正则可提取，探测脚本不需要任何 schema 改动就能跑起来。这一步**已实现**：
  [`scripts/datasets/probe_upstream.py`](../scripts/datasets/probe_upstream.py)，结果写
  `<data root>/probe/seen.json`；
- **figshare 那 14 个来源目前探测不了**，需要人工补一次 figshare article id（`official_url` 指向
  的是项目主页，不含 figshare 标识）。这是一项独立的、可量化的人工工作，不要和 schema 改动混在
  一起做。

### 3.4 硬约束：必须是纯增量改动

`backend/tests/test_dataset_acquisition.py` 对 `status` 做的是**子串**断言，例如
`"user-action-required" in sources["matcloud"]["status"]`（第 135-147 行）、
`sources["mptrj"]["status"] == "excluded-by-scope-trajectory-dataset"`、
`"912-full-and-1267-partial" in sources["opxrd"]["status"]`（第 271-281 行）。

因此：

- `status` 的现有文本语义**不可改写**，新状态只能并列存在；
- 新字段必须全部可选，缺失时按 `state: "registered"` 处理，避免一次性回填 106 条；
- `schema_version` 升到 2，加载处同时接受 1 和 2。

改字段时需同步检查的现有消费方：

- [`scripts/datasets/acquire.py:278`](../scripts/datasets/acquire.py:278)——`--catalog` 默认值；
- [`scripts/properties/registry.py:20`](../scripts/properties/registry.py:20)——`SOURCES_JSON`
  常量，以及第 336 行"source 未在 sources.json 注册"的报错；
- [`scripts/properties/base.py:115`](../scripts/properties/base.py:115)——适配器的 source id
  同时作为 provenance 标签。

## 4. 探测的礼貌规则

这是整个闭环唯一对外产生副作用的环节，规则从严：

- 一次探测只发一个请求（`HEAD` 或最小元数据查询），**绝不为判定版本而重下整包**；
- 优先条件请求 `If-None-Match` / `If-Modified-Since`，`304` 即判定未变更；
- 同一 host 并发 1、间隔 ≥1 秒；`429` / `5xx` 当次放弃，不重试；
- User-Agent 标明项目名与联系方式；遵守 `robots.txt` 与来源服务条款；
- **不绕过账户、付费许可与再分发限制**。需要登录才能看到版本信息的来源一律
  `probe_kind: "manual"`，由人工在复核时更新 `seen`。

频率：先用一个全局间隔（**待定**，量级为周到月），到期即探测。`probe_kind: "manual"` 的来源不
探测，只在到期时提醒人工复核。

## 5. 适配器的验收门槛

"生成或推荐采集与字段映射适配器"必须改写成可判定的门槛。草稿先落在 draft 目录，过门槛并经人工
评审后才进入 [`scripts/properties/adapters/`](../scripts/properties/adapters/)（现有 55 个适配器）。

1. **golden sample 零 diff。** 每个来源固定一份小样本（约 50-200 条原始记录）与期望输出，逐字段
   相同才算过。样本随适配器提交，作为回归基线。单位错、量纲错、字段错位都由这一条兜住。
2. **字段覆盖率 100%。** 上游记录里每个字段要么映射到规范名，要么**显式声明忽略**并写明理由。
   未声明的字段视为失败——否则静默丢字段不会被任何测试发现。
3. **provenance 必填。** `source_id`、`native_id`、`method` 非空。`method` 保留原始泛函或测量
   条件字符串（`PBE` / `r2SCAN` / `experiment` / `GCMC 298K 16bar`），不做归并。
4. **走既有注册路径。** 经 [`registry.py`](../scripts/properties/registry.py) 注册（未注册会触发
   第 336 行的 `source ... is not registered in scripts/datasets/sources.json`），规范名取自
   `CANONICAL_PROPERTIES`，标量回填遵循既有的 `SCALAR_BACKFILL_PRIORITY`，不另起一套机制。

人工评审只看三件自动检查判不出来的事：映射语义是否正确（单位对但含义错的字段，diff 也是零）、
显式忽略的字段是否真的可以忽略、该来源是否有需要复合键的枚举库特性（见第 6.3 节）。

## 6. 快照对外承诺

### 6.1 版本与不可变性

- 快照版本**就是 Hugging Face 的 revision**，不另造版本号命名空间；需要人读的标签时再加 tag；
- **已发布快照不可变**：修正作为新 revision 发布，不原地覆盖。用户引用的版本永远能取回。

### 6.2 material ID 的跨快照稳定性

唯一一旦对外承诺就撤不回的东西：

- 承诺：**同一结构指纹在跨快照之间保持同一 material id。** 新增来源、新增性质、来源下线都不导致
  重编号；下线的 id 不回收、不复用。
- 唯一允许重编号的情况：指纹算法版本变更。此时必须随快照发布 `old_id → new_id` 映射表，并在变更
  报告里标为重编号事件。

### 6.3 去重的确定性

去重使用 BAWL 指纹（`material_hasher.hasher.bawl`）：解析 → 上限 500 site → 化为原胞 → 上限
300 site → 取哈希。性质挂接先权威标识符（`mp-` / `oqmd-` / `agm-` / `icsd-` / `cod-` …）再指纹，
**绝不仅按化学式匹配**。

指纹算法一变，跨快照的合并结果就变，所以快照元数据必须固定记录：`material_hasher` 版本、上述两个
site 上限、以及**复合键例外清单**。枚举库（Deem 假想沸石、hMOF）在同一拓扑上换取代基，兄弟骨架
共享键合图从而指纹碰撞，它们按 `(指纹, 每 site 体积)` 复合键收录、碰撞指纹被刻意排除在匹配表
之外；这份清单属于算法定义的一部分，不记录则换台机器重建会得到不同的合并结果。

`match_via` ∈ `id:<db>` / `hash` / `origin` 的语义见
[`docs/property-integration.zh-CN.md`](property-integration.zh-CN.md)，此处不重复。指纹变更只影响
`match_via = hash` 的挂接，`id:<db>` 不受影响——变更报告按 `match_via` 分别统计。

### 6.4 许可闸门

- **默认拒绝**：授权无法确认的数据不进公开快照，状态 `rejected(licence-unclear)`；
- 受限来源只发布名称、官方链接、公开元数据、source id 与许可状态，不发布受保护的结构、性质字段
  或原始文件；
- 统一格式不改变原始数据的权利归属，自动发现流程必须过同一道闸门；
- 更严格的许可不得经更宽松的数据集"传染式"再分发（SPSE、3DSC-ICSD 等 ICSD 派生镜像按
  properties-only 模式运行，不贡献结构）；
- 当前 Hugging Face 仓库是**私有工作索引**，含 ICSD 以及 CC BY-NC / 学术条款的 ELEMENTA、GNoME、
  AFLOW。公开快照须先按 `source_id` 过滤——每条性质行都记录了 `source_id`，过滤只是一个 `WHERE`
  子句，但尚未应用。

逐来源的许可判定与所需人工步骤见
[`docs/dataset-acquisition.zh-CN.md`](dataset-acquisition.zh-CN.md)，本文件不重复。

### 6.5 快照元数据与变更报告

每个快照携带：索引 schema 版本、第 6.3 节的指纹算法三项、许可清单，以及逐来源的
`(source_id, seen, checked_at)`。有了最后一项，任一快照才能回溯到确切的上游版本——这是"可审计"的
实际含义。

变更报告：新增 / 下线的来源及原因码、每来源记录数与性质行数差值、材料总数的新增与消失、许可状态
变化、本轮被拒收或隔离的来源清单。

**合并关系变化**（曾独立的两条记录被合并、或一条被拆开）需要上一版快照的完整匹配表才能算，成本
明显高于其他项——先只出计数，样例 id 作为可选项，等真的用到再加。

## 7. 实现顺序

原则：**先用只读探测产出真实数据，再让数据决定字段长什么样。** 反过来做就是先建抽象再看需求。

**第 1 步（已实现）：只读探测器，零 schema 改动。**
[`scripts/datasets/probe_upstream.py`](../scripts/datasets/probe_upstream.py) 从现有
`downloads[].url` 提取上游标识，覆盖 31 个来源，结果写 `<data root>/probe/seen.json`，**不碰
`sources.json`、不下载任何数据**。Zenodo 与 Materials Cloud 用
`api/records/<id>/versions/latest` 一次请求即可知道所记录的 record 是否已被新版本取代。

首轮全量运行发现 4 个来源的上游已经领先于目录里记录的 record：`arc-mof`、`carolina`、
`core-mof`（v1.1.3 → v2.0.1）、`topomat`。

→ 验证：`pytest backend/tests/test_upstream_probe.py`；连跑两次，第二次应全部判定"未变更"。

**第 2 步（已完成）：让第 1 步的输出决定字段形态。**
结论是**目录一个字段都不加**——探测状态全部派生，旁路文件才是它的家（第 3.2 节）。`schema_version`
留在 1，只落地一条回归测试：只带六个必填字段的来源必须能通过校验，这是第 3、4 步分批填字段的前提。
→ 验证：`pytest backend/tests` 全绿。

**第 3 步（已完成）：`state` / `reason` 回填。**
101 条已填，5 条留空等政策判断。分布：`integrated` 54（= `adapters/` 里有模块的那 54 个，与 README
的数字一致）、`rejected(account-required)` 21、`acquired` 14、`rejected(no-bulk-interface)` 7、
`rejected(scope-trajectory)` 3、`rejected(join-key-missing)` 1（Catalysis-Hub）、`registered` 1
（Atomly，采集在途）。`schema_version` 升到 2，`validate_catalog` 校验状态与原因码的配对：终态必须
带已知原因码，非终态不得带原因码，有 `reason` 无 `state` 直接报错。
→ 验证：`pytest backend/tests`（140 passed）；`status` 文本零改动。

留空的 5 条需要的不是规则而是决定，见第 2.2 节末：`nomad`、`optimade`、`perovskite-database`、
`open-materials-db`、`topological-materials`。

**第 4 步（可与第 3 步并行）：补 figshare article id。**
14 个来源，人工一次性工作，补完这 14 条才进入探测覆盖。
→ 验证：14 个来源的探测结果从"无法探测"变为有 `seen` 值。

**第 5 步：golden sample 框架与第 5 节门槛检查。**
→ 验证：拿一个现有适配器反向跑通，故意改坏一个字段应当报错。

**第 6 步：快照元数据与变更报告（第 6.5 节）。**
→ 验证：对同一份索引连出两次报告，差异应为空。

**第 7 步：适配器草稿生成。**
放在最后——前六步没落地时，它产出的东西无从判定对错。
