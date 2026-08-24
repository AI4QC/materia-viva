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
[0] 发现候选新来源（不在目录里的数据库）
        │ 产出：候选条目 + 证据链接，落入 state=registered
        │ 脚本做不到这一步——它无法发现一个不在目录里的数据库
        ↓
[1] 探测上游 → 与上次看到的 seen 比对（仅已在目录里的来源）
        │ 不同 → 继续；相同 → 只更新 checked_at，本轮结束
        ↓
[2] ✋ 许可、访问方式、静态结构范围、轨迹污染判定
        │ 授权不明 → rejected(licence-unclear)（默认不发布，见第 6.4 节）
        ↓
[2.5] 产出拉取计划（downloads[] 的一个 diff）或起草拉取脚本
        │ HEAD 逐个 URL 核对存在性与 content-length；容量余量检查
        │ 已过闸门的来源升级 → 可直接交 acquire.py 执行
        │ 全新候选 → 停在计划，等 [2]
        ↓
[2.9] acquire.py 执行下载（余量保护 / 可恢复 / 写凭据）
        │ 只算结构指纹，与现有池子求重叠 → 「新增唯一结构 N / 候选总数 M」
        ↓
[2.95] ✋ 准入批准：专家据测量结果决定收不收
        │ 重叠过高 / 解析失败率过高 → rejected（第 1.10 节）
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

关键差别是人工闸门有四个（[2] [2.95] [4] [7]），不是 README 图里末尾唯一一个。许可判定和适配器评审都在
数据进入索引之前——事后批准挡不住已经污染的映射。

### 1.1 谁执行哪一步

闭环里有三类执行者，混淆它们是这套设计最容易出的错。

| 步骤 | 执行者 | 为什么是它 |
|---|---|---|
| [0] 发现候选新来源 | **agent** | 需要读文献、读网页、判断"这是不是一个晶体结构数据库"；脚本无法发现目录外的东西 |
| [1] 探测上游版本 | 脚本 | 纯确定性比较，已实现（`probe_upstream.py`） |
| [2] 许可判定 | **人** | 法律判断，且错了不可逆（数据一旦发布收不回） |
| [2.5] 产出拉取计划 | **agent** | 读上游文档判断"下载哪些文件、放哪里"；这是历史上最大的人工瓶颈，24 个采集脚本里约 22 个是为单个来源手写的 |
| [3] 起草采集与字段映射适配器 | **agent** | 读上游文档与样本、写映射代码，正是它擅长的 |
| [2.95] 准入批准 | **人** | 据去重测量决定收不收，见第 1.10 节 |
| [4] 适配器评审并注册 | **人** | 只看三件自动检查判不出来的事，见第 5 节 |
| [5] [6] 统一、去重、校验 | 脚本 | 确定性流水线 |
| [7] 发布批准 | **人** | 对外承诺 |

### 1.2 收容规则：agent 可以提议任何东西，但没有东西凭 agent 的话入库

这不是原则性表态，是这套仓库已经在按它运行的规则，三个现成的先例：

- **`integrated` 不是自称。** 它的定义是"`scripts/properties/adapters/` 里存在对应模块"，由测试钉住
  两个集合相等。agent 说某来源整合好了不算，文件存在才算。
- **figshare article id 不靠搜索结果采信。** 第 4 步里 9 个映射全部用"该 article 的元数据列出了我们
  早已记录的 file id"反证过。搜索给出的候选只是候选，file id 对上才入库；4 个对不上的至今留空。
- **适配器不靠人读代码放行。** 第 5 节四条门槛里最硬的是 golden sample 零 diff——不管草稿是谁写的，
  逐字段对不上就是不通过。

由此得到 agent 的边界，**这几条比 agent 本身怎么实现重要得多**：

- agent 只能产出 `registered` 状态的候选、以及 draft 目录里的适配器草稿；
- agent **不得**写索引、不得改已发布快照、不得推进任何来源的 `state`（推进由脚本按可验证事实做，
  或由人在闸门处做）、不得做许可判定；
- agent 的每一个论断都必须落成一个**不依赖 agent 的检查**：文件存在、id 对上、diff 为零。做不到
  这一点的论断，只能进人工闸门排队，不能自动通过。

本文件第 1-4 步就是按这个模式做的（agent 起草 + 人工闸门 + 机器可验证的事实），包括这一节。

**本节不设计 agent 本身**——模型选择、提示词、自治程度、调度方式都还没有依据可谈，写下来只会是猜测。
需要先有的是上面那条边界，因为它决定了 agent 出错时损害的上限。

### 1.3 agent 具体怎么组织：按目标冲突拆，不按步骤拆

自我进化由 agent（乃至多 agent）实现，但**判据不是"多放几个 agent"，而是：只在目标冲突的地方拆成
两个。目标不冲突的地方，第二个 agent 只是第二次幻觉的机会。**

这条判据有一次可观测的实测。第 2 步与第 1 步审查是两个并行 subagent 做的：一个消耗约 85k tokens，
推翻了本文件 §3.2 原本的设计（结论是目录一个字段都不加）并挑出三处事实错误；另一个约 69k tokens，
找到两个真 bug（失败探测擦掉基线、`--catalog` 崩在写文件前），同时给出一个错误判断。有效的原因很
具体——**第二个 agent 的任务是攻击第一个的前提**；而那个错误判断说明**收益是伴随验证成本来的**，
无人核对的多 agent 只是更快地产出更自信的错误答案。

#### 三对真正冲突的角色

| 拆分 | 为什么必须拆 |
|---|---|
| 起草适配器 ↔ 写 golden sample | 同一个 agent 既写映射又写期望输出时，**零 diff 毫无意义**——它会把期望输出写成迎合自己 bug 的样子。必须 A 读上游文档写适配器、B 独立读同一份文档写期望输出，且 B 看不到 A 的代码。这是 §1.2 规则升一层：检查者与被检查者分离 |
| 发现来源 ↔ 反驳候选 | 发现方目标是找到东西，天然有产出偏向。反驳方专门问：这真是晶体结构库吗、许可真的开放吗、是不是已被现有来源覆盖。`open-materials-db`（主来源 COD 已整合、本身冗余）就是这种形态，再搜一遍发现不了，得有人专门想否掉它 |
| 映射语义 ↔ 单位与量纲 | 第 5 节人工评审要看的"单位对但含义错"可以拆出一个只管量纲的角色。比前两条弱，可后做 |

#### 明确不做 MAS 的地方

- **步骤 [1] [5] [6]**（探测、统一、去重）是确定性脚本且已在跑。让 agent 去指挥它们只增加一种新
  失败方式（agent 跑错脚本），没有上行收益。
- **不设 manager agent 编排流水线。** 编排形状写在**脚本**里：哪一步 fan out、几路、结果怎么汇总，
  都是可审计的代码，每次运行一样。**judgment 归 agent，workflow 归脚本。**
- **许可判定不拆。** 两个 agent 不会让法律判断更可靠，它需要人（步骤 [2]）。

#### 运行形态

- **harness 是 Claude Code 的 subagent**，不自建框架。仓库里已有 `.claude/CLAUDE.md` 与 `.mcp.json`，
  agent 因此免费获得本仓库的约定；发现来源所需的 web 检索也由 harness 提供。自建 API 循环等于为一个
  两人维护的科研数据集重建工具调用、重试与沙箱。
- **产出单位是一个分支 + 一个提交 + 一份报告**，不是数据库写入。理由是实测的：第 1-4 步里每一个
  人工闸门，实质上都是人在读 diff。这也让 §1.2 的"损害上限"变成一个具体的东西——一个未合并的分支，
  `git revert` 即可撤销。
- **触发先只手动**（在存放数据的那台机器上跑）。agent 还没跑过一次就先建调度，是把顺序搞反了；且
  探测基线是机器本地的（第 3.2 节），CI 跑不了那一半。

#### 发现 agent 的输出如何被机器验证

§1.2 要求每个论断落成不依赖 agent 的检查。对一个候选数据库，可查的是：

| 检查 | 可机器执行 |
|---|---|
| `official_url` 解析且返回 200 | ✅ |
| 不与目录现有条目重复（host + 名称） | ✅ |
| 存在可解析的许可声明 URL | ✅（URL 存在可查；内容判断留步骤 [2]） |
| `validate_catalog` 通过 | ✅ |
| `plan_probe` 能否探测它 | ✅ 免费，且直接回答"它能不能进入闭环" |
| 声称的记录数、是否真是晶体结构库 | ❌ 只能是 claim，必须标记为 claim 进人工闸门 |

**拒收记忆不需要新建台账。** 目录里已有 36 条 `rejected`，发现 agent 对全量 `sources.json` 去重，
就自动不会重复提议已被否掉的来源——`state` 回填（第 3 步）顺带把这件事解决了。

### 1.4 MAS 的三种产出，与"谁真的去拉数据"

MAS 的实际用途是：**搜索新来源与升级 → 产出拉取计划 → 交专家 check**。三种产出风险递增，闸门也不同。

#### 产出一：候选来源

落成 `state=registered` 的目录条目 + 证据链接。机器检查见第 1.2 节末的表。

#### 产出二：拉取计划（最有价值的一种）

注意这一种主要针对**新来源**。已采集来源的版本升级默认不走 MAS，按文件名重叠度分流，见第 1.9 节。

**格式不需要发明——它已经在目录里**：`downloads: [{filename, url, bytes}]` 加 `data_path`。所以一份
拉取计划就是对这个数组的一个 diff，而且可以完全不靠 agent 的话来验证：

| 检查 | 靠什么 |
|---|---|
| URL 是 https、filename 是安全相对路径、bytes 是非负整数 | `validate_catalog` 已在做 |
| 每个 URL 真的存在，且 content-length 与声称的 `bytes` 一致 | 逐个 HEAD，一次请求 |
| 下载后不会吃掉 SSD 安全余量 | `acquire.py` 的 `ensure_capacity`（50 GiB 保留）已在做 |
| `data_path` 不与现有来源冲突 | 目录内比对 |

也就是说，第二种产出几乎不需要新代码——需要的是让 agent 填这个数组，然后跑一遍已有的校验加一轮 HEAD。

#### 产出三：拉取脚本

约 22 个来源没有静态文件清单（分页 API、GraphQL、需登录、逐条端点），拉取计划表达不了，必须起草脚本。
风险最高，闸门与适配器同级（第 5 节）：拿一小段真实响应做 golden sample，由**另一个** agent 独立
写期望输出。

### 1.5 谁真的执行拉取：`acquire.py`，不是 agent

`scripts/datasets/acquire.py` 已经提供了三样 agent 直接 curl 就会丢掉的东西：50 GiB SSD 安全余量
（`ensure_capacity`）、可恢复下载（`run_curl_resumable`）、以及下载凭据（`write_receipt`）。所以
agent 不自己拉数据，它产出计划，由 `acquire.py` 执行。

**什么时候可以"直接拉"**，取决于许可闸门过没过，而这个由 `state` 回答：

- 来源已过闸门（`state` 为 `acquired` / `integrated`）而上游发了新版本 → **可以直接拉**，因为许可
  判定没有变化，拉的是同一个来源的新版本；
- 全新候选（`state=registered`） → **必须停在计划**，等步骤 [2] 的许可判定。数据一旦下载并进入索引，
  许可判断错了收不回来。

### 1.6 交给专家 check 的是什么

不是对话记录，是**一个 diff 加一份固定清单**。清单不是凭空拟的，每一条都对应目录里一个真实条目——
这五件事都是专家会抓住、agent 不会抓住的：

| 要 check 的 | 真实先例 |
|---|---|
| 拉的是静态结构端点，还是轨迹中间帧 | `elementa`（一次弛豫只取端点，43.5M 帧收 2.2M）、`mptrj` / `omat24`（`scope-trajectory` 直接排除） |
| 关联键齐不齐，数据挂得上吗 | `catalysis-hub`（抓取漏了 `reactionSystems`，91% 反应挂不上，已下载仍被拒） |
| 该排除哪些字段 | `spse`（`excluded_structure_fields`: migration-path arrays） |
| 许可与再分发边界 | `icsd` / `elementa` / `gnome` / `aflow`（受限，不进公开快照） |
| 是否与现有来源冗余 | `open-materials-db`（主来源是 COD，已整合） |

### 1.7 MAS 的搜索靶子：探测器到不了的那 66 个

探测器已经用一次 HTTP 请求确定性地覆盖 40 个来源。**不要派 agent 去重做这 40 个**——更慢、更贵、更
不可靠。MAS 搜索的目标是：

- **66 个探测不到的来源**（仅浏览接口、逐条下载、需注册、联邦查询、以及 5 个未解的 figshare）——判断
  它们有没有发新版本本身就是一个需要读页面、读论文的任务；
- **不在目录里的新数据库**——脚本原理上做不到。

### 1.8 怎么给 MAS 留空间：先建验证器，不建脚手架

先把闭环的其余部分写好、给 MAS 留出位置，之后再计划自动化 agent——这个顺序是上面那条规则的直接
推论。但"留位置"有一个具体的做法，也有一个具体的陷阱。

**做法：把每个 agent 角色的验证器先建出来，生产者留空。** 理由是不对称的——生产者的形状是我们目前
知道得最少的东西（哪种拆分、什么提示、多少轮），而验证器的形状由"什么必须为真"决定，而这个现在
就已经确定：

| 数据契约 | 它的验证器 | 今天对人有用吗 |
|---|---|---|
| `downloads[]` + `data_path` | `validate_catalog` + 逐 URL HEAD + `ensure_capacity` | 有：人手写的拉取计划走同一道检查 |
| 候选来源条目 | 第 1.2 节那五条 | 有：人添一个新来源时同样该过 |
| 适配器 + golden sample | 零 diff 回归 | **有，而且最急**：55 个适配器目前零测试覆盖 |

验证器一旦存在，agent 接进来就只是"换一个生产者"，契约与闸门一行都不用改。这才是"空间"的实体。

**陷阱：不要建 `agents/` 目录、提示词模板、模型配置或编排框架。** 那些全都是关于生产者的猜测，而
生产者恰恰是唯一还没有依据的部分。写下来的猜测会变成后来者以为的约束。空目录和 stub 不是空间，
它们是提前做错的决定。

### 1.9 升级路径：让文件名重叠度决定要不要动用判断

**已在目录、已采集的来源发新版本时，默认不走 MAS。** 但判据不是"拉取过还是新来源"，而是一个更硬、
而且一个 API 调用就能算出来的事实：**新版本的文件名集合，与目录里记录的还能不能对上。** 这个数先算，
再决定是否动用判断。

实测那三个 zenodo 落后来源，正好落在三种情况上：

| 来源 | 旧文件名在新版本中的存留 | 路径 |
|---|---|---|
| `carolina` | 1/1 全在 | **纯机械**：替换 record id，逐 URL HEAD 验证即可。零 agent |
| `arc-mof` | 23/24 在，`ARCMOF_20220610.tar.gz` 消失，新版本共 25 个文件 | **机械推导 + 标出 delta**：专家只回答"消失的那个和新增的那些怎么办"。零 agent |
| `core-mof` | **0/2**，v1.1.3 的两个 csv 在 v2.0.1 里一个都不在，新版本是 9 个完全不同的文件 | **上游重构**：必须有人判断 9 个新文件里哪些对应我们原来取的东西。这才是 MAS 或专家该上的地方 |

这套分流已实现：[`scripts/datasets/plan_upgrade.py`](../scripts/datasets/plan_upgrade.py)。它按 kind 取
上游最新版本的文件清单、算重叠度、产出可直接粘进 `downloads[]` 的计划，并逐 URL HEAD 核对存在性与
content-length。**它不写目录**——产出是一份待审的提案。

由此得到三条路由，按重叠度自动分流：

- **全部同名** → 计划是机械替换。来源已过许可闸门（第 1.5 节），可直接交 `acquire.py`；给专家的只是
  一行通知。
- **部分同名** → 机械推导已同名的部分，把消失与新增的文件单列出来。专家的问题被收窄到那个 delta，
  而不是重审整个来源。
- **零同名** → 上游改了结构。这时才需要判断，也才值得动用 MAS。

一个实现中踩到的坑值得记：**比对必须只针对被探测那个上游负责的文件。** `carolina` 从 zenodo 取一个
归档、又从一个 Hugging Face 数据集取两个 parquet；拿全部三个去和 zenodo 的清单比，那两个 HF 文件会
被判成"消失"，把一个 `mechanical` 误报成 `delta`，让专家去追一个不存在的问题。其他 host 的文件数会
如实报出，但不参与比对。

**升级路径里唯一真正新增的风险是许可可能变。** 数据集在两个版本之间换许可是会发生的，而 invenio 与
figshare 的 API 都返回许可字段，所以这一项可以机器比对——但要归一化后再比：实测三个来源上游返回
`cc-by-4.0`，目录里记的是 `CC BY 4.0`，朴素字符串比较会误报。归一化后仍不一致的，必须回到步骤 [2]
的人工许可判定，不能因为"这个来源以前过闸门了"就放行。

**66 个探测不到的来源另当别论**：判定它们有没有发新版本本身就需要读页面、读论文，那一步需要 agent
（第 1.7 节）。但一旦判定"有新版本"，它的采集形状仍然是已知的——**MAS 用在"判定有没有变"，不用在
"怎么拉"。**

### 1.10 准入：先测量重叠，再请专家批准

新数据集会一直出现，所以闭环里必须有一条常设的"发现—拉取—去重—批准"通道。这条通道有三个决定。

#### 两种周期性活动要分开

| 活动 | 周期 | 执行者 | 覆盖 |
|---|---|---|---|
| 探测已有来源有没有新版本 | 每来源，周到月量级 | 脚本，确定性 | 40 个（已实现） |
| 搜索目录里没有的新数据集 | 每周或每月一次全局扫 | **agent** | 整个互联网 |
| 判定 66 个探测不到的来源变没变 | 随上一条同批 | **agent** | 66 个（第 1.7 节） |

混为一谈会付两次代价：让 agent 去重做那 40 个确定性探测既慢又贵，让脚本去搜新数据集则根本做不到。

#### 冗余从"意见"变成"测量"

`open-materials-db` 当初是靠读它的文档、判断"主来源是 COD、我们已整合"而被拒的——一个意见。有了
去重通道之后，这件事变成一个数：拉取之后只算结构指纹，与现有池子的指纹集求交，得出**「新增唯一结构
N / 候选总数 M」**。

这正是第 1.2 节要的那种检查——**一个 agent 编不出来的数**。所以准入批准的依据是测量，不是叙述。

已实现：[`scripts/properties/measure_overlap.py`](../scripts/properties/measure_overlap.py)。它读
`scripts/properties/hashing.py` 已有的指纹输出（`native_id / n_sites / formula / bawl_hash`，失败记为
`FAIL:<reason>`），因此**不重实现指纹协议**；池子一侧以只读方式打开
`data/props_work/match_map.sqlite` 的 `hash_map`。产出正是下面那四行测量，例如：

```text
读入 340 行，解析失败 15 (0.0441)
  FAIL:TOO_LARGE × 12
  FAIL:DISORDERED × 3
唯一指纹 320，池中已有 300，新增 20 (0.0625)
  与 cod 重叠 300 个材料
  与 icsd 重叠 100 个材料
```

`id_map` 只建了 `(source, native_id)` 索引，没有 `material_id` 索引，所以按来源拆分要扫它一遍——
这是拿到"与哪些现有来源各重叠多少"的代价，一次全表扫。

#### 关键结论：准入只需要结构，不需要性质

要算重叠就得把结构从拉下来的数据里解析出来——但**只要结构**。第 5 节那套带 golden sample 的性质
适配器（最贵的一块）在准入决定之前**不需要存在**。现成的零件已经够：CIF → BAWL 指纹在
`scripts/properties/hashing.py`，extxyz → BAWL 在 `scripts/datasets/elementa_hash.py`，而"取现有池子
的参考指纹集"在 `scripts/datasets/elementa_merge.py` 里已是成熟套路。

于是顺序是：

```
✋ 许可判定 → 拉取 → 仅结构指纹 → 测量重叠 → ✋ 准入批准 → 才写性质适配器
```

**也就是说，永远不会为一个最终被拒的数据集写完整适配器。** 这是这条通道最省的地方。

#### 专家在准入闸门看到什么

第 1.6 节那份清单，加上四行测量结果：

| 测量项 | 为什么它能决定收不收 |
|---|---|
| 新增唯一结构 N / 候选总数 M | 冗余的直接证据 |
| 与哪些现有来源重叠、各多少 | 分辨"整体重复"与"补充了某个化学空间" |
| 解析失败比例 | 失败率高本身就是拒收信号（格式不规整、字段缺失） |
| 轨迹 / 中间帧占比 | 对应第 1.6 节 `elementa` 那一行，静态端点规则 |

#### 一个要等测量到位才该加的原因码

`open-materials-db` 现在记的是 `scope-unbounded`，但它真实的原因是冗余。等这个测量存在了，
`redundant-with-pool` 才有可验证的定义（重叠高于阈值），那时再加进第 2.2 节的词表。现在加，它只是
一个无法验证的标签——违反"新码只在真的出现新失败形态时增加"。

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
| `scope-unbounded` | 有批量接口，但主动不做无边界全量镜像 | NOMAD、Perovskite Database、Open Materials DB |
| `join-key-missing` | 抓取缺少关联键，数据无法挂接 | Catalysis-Hub |
| `integrity-failed` | 校验和、计数或异常值检查未通过 | 见采集文档第 6 节 |

新码只在真的出现新失败形态时增加，不预先铺开。回填之后 `licence-unclear` 和 `integrity-failed`
仍是零实例，因为它们是**运行期结果而非目录类别**：前者是许可闸门的默认拒绝出口，后者由完整性检查
在 `quarantined` 时写入。目录里出现零实例是正常的。

`scope-unbounded` 就是回填时被数据逼出来的：`nomad` 的 status 是 `too-large-for-full-mirror`
——它有批量接口，是我们主动不做全量镜像，记成 `no-bulk-interface` 是不准确的。同一类还有
`perovskite-database`（经 NOMAD 查询访问，只登记）和 `open-materials-db`（主来源 COD 已整合，本身
冗余），正对应 [`docs/dataset-acquisition.zh-CN.md`](dataset-acquisition.zh-CN.md) 第 4 节
「已探测但不做无边界全量镜像」那一类。

另两条同批定下：`optimade` 记为 `acquired`（registry 已采到并校验，只有联邦的 provider 数据不
镜像），`topological-materials` 记为 `rejected(licence-restricted)`——它同时是"只有浏览接口"和
"不可再分发"，后者是更硬的约束。

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
| `ndownloader.figshare.com` | 14 | ⚠️ 文件 id 不随版本移动；9 个已解出 article id，5 个未解 |
| `zenodo.org` | 8 | ✅ `api/records/<record_id>/...` |
| `archive.materialscloud.org` | 5 | ✅ `api/records/<record_id>/...` |
| `huggingface.co` | 3 | ✅ `datasets/<repo>/resolve/main/...` |
| github（raw / media / codeload / archive） | 5 | ✅ `<org>/<repo>/<branch>/...` |
| 其余单点 host | 10 | 逐个看，多数只能 `http-head` |

`http-head` 一次只探第一个下载 URL（礼貌规则：一次探测一个请求）。`cmr-static` 有 27 个下载
URL、`rruff` 16 个、`mofx-db` 6 个，对它们而言这是**局部覆盖**——探测结果会在 note 里写
`head-covers-1-of-N-files`，不让局部覆盖读成全覆盖。

两条直接结论：

- **40 个来源可探测**（invenio-latest 13、http-head 11、figshare-article 9、git-commit 5、
  hf-revision 2）。其中 38 个的上游标识可从现有 URL 提取，2 个是查出来记进目录的。这一步**已实现**：
  [`scripts/datasets/probe_upstream.py`](../scripts/datasets/probe_upstream.py)，结果写
  `<data root>/probe/seen.json`；
- **figshare 那 14 个来源里 9 个已解决**（第 4 步）：7 个的 article id 本来就在 `official_url` 里，
  按第 3.2 节的规则不入目录、由 `plan_probe` 提取；另 2 个（`jarvis-dft`、`hex-high-pressure`）查出
  来才知道，属于人工知识，记为目录字段 `figshare_article`。剩 5 个仍未解，见第 7 节第 4 步。

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

适配器草稿由 **agent** 起草（第 1.1 节），所以"生成或推荐采集与字段映射适配器"必须改写成可判定的
门槛——评审一段生成代码的正确性，靠读是读不出来的，只能靠对比输出。草稿先落在 draft 目录，过门槛
并经人工评审后才进入 [`scripts/properties/adapters/`](../scripts/properties/adapters/)（现有 55 个适配器）。

1. **golden sample 零 diff，且期望输出必须独立撰写。** 每个来源固定一份小样本（约 50-200 条原始
   记录）与期望输出，逐字段相同才算过。样本随适配器提交，作为回归基线。单位错、量纲错、字段错位都
   由这一条兜住。
   **但只有在期望输出不是写适配器的那一方产出时才成立**——同一个作者会把期望输出写成迎合自己 bug
   的样子，那时零 diff 只证明它自我一致。所以起草与期望输出由两个 agent 分别读同一份上游文档产出，
   后者看不到前者的代码（第 1.3 节）。
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
106 条全部填完。分布：`integrated` 54（= `adapters/` 里有模块的那 54 个，与 README 的数字一致）、
`rejected(account-required)` 21、`acquired` 15、`rejected(no-bulk-interface)` 7、
`rejected(scope-unbounded)` 3、`rejected(scope-trajectory)` 3、`rejected(licence-restricted)` 1、
`rejected(join-key-missing)` 1（Catalysis-Hub）、`registered` 1（Atomly，采集在途）。`schema_version` 升到 2，`validate_catalog` 校验状态与原因码的配对：终态必须
带已知原因码，非终态不得带原因码，有 `reason` 无 `state` 直接报错。
→ 验证：`pytest backend/tests`（140 passed）；`status` 文本零改动。

其中 5 条需要的是决定而不是规则，为它们新增了一个原因码 `scope-unbounded`，见第 2.2 节。

**第 4 步（已完成）：figshare article id。**
14 个 figshare 来源里 9 个可探测了，覆盖从 31 升到 40/106。

关键点是 article 的元数据会列出它的 files，所以**每个映射都能用我们记录的 file id 反证，而不是靠
标题猜**——这是 article id 敢入库的前提。三条来路：

| 来路 | 数量 | 存在哪 |
|---|---:|---|
| article id 已在 `official_url` 里 | 7 | 不入库，`plan_probe` 提取（同第 3.2 节规则） |
| figshare 搜索反查 + file id 验证 | 1 | `jarvis-dft` → `figshare_article: 6815699` |
| collection 里唯一那篇 article | 1 | `hex-high-pressure` → `figshare_article: 25403968` |

`hex-high-pressure` 的 `official_url` 是 collection（`7119778`），**不是** article（`25403968`）
——所以 `plan_probe` 只匹配 `/articles/` 路径，绝不匹配 collection，并且记录值优先于 URL 推导。

**未解的 5 个**：`aflow`、`c2db`、`2dmatpedia`、`omdb-organic`（项目主页与 figshare 搜索都没给出
能被 file id 验证的 article）、`jarvis-specialized-structures`（16 个 file id 分散在多篇 article，
一条目录记录对多篇文章，单个 `figshare_article` 字段表达不了）。它们保持
`manual / figshare-article-id-unknown`，等谁手上有确切链接再补一条即可。

→ 验证：`pytest backend/tests`（143 passed）；9 个来源实跑均取到 article version 作为 `seen`。

**第 5 步：golden sample 框架与第 5 节门槛检查。**
包含第 1.3 节那个拆分：起草与期望输出由两个互不可见的 agent 产出，否则零 diff 只证明自我一致。
→ 验证：拿一个现有适配器反向跑通，故意改坏一个字段应当报错。

**第 5.5 步（已完成）：准入的重叠测量。**
[`scripts/properties/measure_overlap.py`](../scripts/properties/measure_overlap.py)，第 1.10 节。
纯脚本、零 agent，复用既有指纹协议与 match map。
→ 验证：9 个测试（含"整个候选池子都已有"这种 `open-materials-db` 形态、以及只读打开 match map 的
断言）；本机没有真实索引，端到端只在合成 fixture 上跑过，**真实验证要在存数据那台机器上执行**：
`python scripts/properties/measure_overlap.py --hashes <候选的 hashes.tsv.gz> --source <id>`。

**第 6 步：快照元数据与变更报告（第 6.5 节）。**
→ 验证：对同一份索引连出两次报告，差异应为空。

**agent 角色的落地顺序，由"验证机制在不在"决定，不由步骤编号决定。**

规则是同一条：**先有验证机制，再有产出它的 agent**，顺序颠倒等于把 agent 的错误当成数据。按这条
规则排下来，三个角色分在两侧：

| agent 角色 | 它的验证机制 | 现在能不能做 |
|---|---|---|
| 拉取计划（[2.5]，产出二） | `validate_catalog` + 逐个 HEAD + `ensure_capacity`，**全部已存在** | **能，不必等第 5 步** |
| 发现候选来源（[0]） | 第 1.2 节那五条检查 + 人工许可闸门，均已存在 | 能 |
| 起草适配器 / 拉取脚本（[3]、产出三） | golden sample 框架 —— **不存在** | 必须等第 5 步 |

所以先做的是**拉取计划 agent**：它是唯一一个验证机制已经齐备的角色，而且对着历史上最大的人工瓶颈
（24 个采集脚本里约 22 个为单个来源手写）。发现 agent 可紧随其后，它的损害上限只是"专家白看一条
候选"。起草类 agent 放最后。
