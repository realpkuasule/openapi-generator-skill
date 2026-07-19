# OpenAPI Engineering 自我改进系统需求规格

> 状态：已批准需求基线（待实现）
> 日期：2026-07-19
> 核心 Skill：`openapi-engineering`
> 维护 Skill：`openapi-engineering-maintainer`
> 目标平台：Codex、Claude Code
> 适用范围：个人自用、M4/M2/MBP14 三机协同

## 1. 背景与问题

`openapi-engineering` 已具备 Contract-First、交互式边界批准、工具中立决策、双平台
评测和可验证完成报告，但目前缺少一个低摩擦、默认私密的真实使用反馈闭环。仅靠人工回忆
会漏掉重复问答、边界误判、工具选择被推翻、平台漂移、未验证项和资源异常；直接保存完整
对话或让 Skill 自动修改自身又会扩大隐私、权限和内存风险。

本扩展建立以下闭环：

```text
真实使用
  → 结构化完成事实
  → 本地记录与字段白名单脱敏
  → 私有 Git 汇总
  → 确定性阈值检测
  → 受控 AI 分析
  → 私有改进候选
  → 精确摘要批准
  → Contract-First + TDD 正式改进
```

系统首先服务唯一项目负责人本人，不建设公共遥测服务，不以调用量、生成代码量等虚荣指标
替代真实决策质量。

## 2. 已确认的产品决策

1. 新建独立 `openapi-engineering-maintainer` Skill；原 Skill 不直接分析或修改自身。
2. 使用双层存储：本机保存较完整事件，私有 Git 只接收校验和脱敏后的事件与汇总。
3. 每次调用自动记录客观事实；异常必问，普通成功每 5 次确定性抽样一次主观反馈。
4. 自动化只写本地或私有分析区；不得自动修改公开源码、创建公开 Issue/分支/PR 或发布。
5. 每周先运行确定性统计；只有命中明确阈值才允许自动启动 AI。
6. 采集默认关闭；本地采集和远端同步分别显式启用。
7. 同步使用平台无关的标准 Git remote，不依赖 GitHub/GitLab API。
8. 日常使用尽力记录；严格评测与资源问题使用可选 launcher 获取确定性指标。
9. 本机详细事件保留 90 天，远端脱敏事件保留 1 年，汇总、确认 incident 和 promoted eval
   长期保留。
10. 自动触发使用确定性平衡档阈值；AI不能自行扩大触发范围。
11. 默认由 Codex 主分析；仅在风险条件下串行调用 Claude Code 独立复核。
12. M4 是唯一协调节点；M2、MBP14 只采集和同步，M4 离线时不转移 AI 权限。
13. M4 使用 `launchd` 每日执行低资源 due 检查，每个 ISO 周最多一次正式汇总。
14. P0 交付端到端最小闭环，P1 加固双平台/launcher/恢复，P2 完成 promoted eval 与趋势优化。
15. 私有候选进入正式项目前必须批准绑定完整输入和文件范围的不可变 SHA-256 proposal。

## 3. 目标与非目标

### 3.1 目标

- 自动收集不依赖主观回忆的结构化使用事实。
- 用一次选择即可补充不能由机器推断的满意度与主要摩擦。
- 在三台机器之间聚合经过脱敏的数据，不同步原始项目内容。
- 用确定性规则发现高价值问题，再让 AI 做语义聚类、根因分析和候选草拟。
- 把已批准问题转化为可追溯的契约、eval、失败测试和 TDD 实施输入。
- 保持 Codex/Claude 双平台可比性，并显式区分尽力采集与严格 launcher 证据。
- 在自动分析时限制模型并发、样本量、超时和子进程资源，避免再次造成内存不足。

### 3.2 非目标

- 不建立公共 SaaS、数据面板、账号系统或中心化遥测服务。
- 不默认保存完整对话、Prompt、源码、OpenAPI 正文、命令输出、环境变量或凭据。
- 不让 AI 推断或伪造用户满意度。
- 不让自动分析直接修改源码、契约、测试、CI、GitHub、npm 或目标项目。
- 不自动创建远端仓库、管理 Git 凭据或修改用户全局 Git 配置。
- 不在普通 PR/日常记录中运行 OpenAPI Generator JAR 或双模型评测。
- 不把一次普通偏好自动升级为产品缺陷。
- P0 不提供 M4 协调权自动故障转移。

## 4. 参与者与三机拓扑

| 参与者 | 职责 | 禁止事项 |
|---|---|---|
| `openapi-engineering` | 完成工作、产生结构化事实、按规则询问一次反馈 | 分析趋势、修改自身、扩大使用记录权限 |
| 本地确定性运行时 | 配置、记录、脱敏、汇总、阈值、保留、Git 同步 | 读取未列入白名单的数据、调用模型、执行远端内容 |
| `openapi-engineering-maintainer` | 消费脱敏触发包，生成私有分析和 proposal | 未批准写公开仓库、把 AI 结论当用户批准 |
| M2/MBP14 collector | 记录本机事件并同步各自分区 | 启动自动 AI 分析、接管协调权 |
| M4 coordinator | due 检查、全局汇总、阈值检测、受控 AI | 并发启动模型、离线时委托其他机器接管 |
| 项目负责人 | 启用采集/同步、评价、批准 proposal、决定正式改进 | 无；负责人是唯一策略批准人 |

设备只使用用户配置的别名（默认建议 `m4`、`m2`、`mbp14`），不得同步硬件序列号、MAC、
完整主机名或账号名。

## 5. 运行状态机

### 5.1 授权状态

```text
disabled
  → usage enable 的 dry-run
  → usage enable --apply
  → local-enabled
  → sync configure 的 dry-run
  → sync configure --apply
  → sync-enabled
```

- 安装或升级不得自动改变授权状态。
- `local-enabled` 只授权写入约定的本地 state root。
- `sync-enabled` 只授权向一个已批准 remote/branch 写入脱敏白名单路径。
- remote、branch、设备别名、state root 或数据分类变化必须重新 dry-run + `--apply`。
- 禁用后立即停止新增记录；历史数据只按单独批准的清理计划删除。

### 5.2 单次使用

```text
best-effort begin（可用时）
  → openapi-engineering 正常工作
  → Completion Report
  → 本地 Usage Event
  → 判断是否询问反馈
  → 脱敏事件进入 outbound queue
  → 同步失败则保留队列并重试，不影响原任务结果
```

普通 Skill 调用无法证明的耗时、峰值 RSS、平台版本等字段必须显式记录为 `unavailable`，不得
估算。launcher 模式必须记录 `capture_mode: launcher` 和实际测量来源。

### 5.3 周期维护

```text
launchd due check
  → 周期是否已处理
  → 拉取并校验脱敏事件
  → 生成确定性 summary
  → 计算 trigger findings
  → 无命中：完成，不调用 AI
  → 有命中：Codex 主分析
  → 风险条件命中：Claude 串行复核
  → 写私有 analysis/candidate/proposal
  → 等待负责人批准精确 digest
```

每个周期使用 `YYYY-Www` ISO week ID 与输入 digest。相同周期和输入必须幂等；M4 离线后只在
下次可用时补跑未完成周期，不把协调权转移给其他机器。

## 6. 系统组件

### 6.1 运行 Skill

更新 `openapi-engineering` 的 Completion Report 流程：

- 在全局采集已启用且本地运行时可用时，提交机器可验证的完成事实；
- 记录失败不得覆盖、延迟或改变原任务的真实完成结论；
- 根据确定性抽样规则决定是否附加一次反馈问题；
- 不读取历史趋势，不调用维护 AI，不写私有远端；
- 找不到运行时或采集关闭时静默跳过写入，但在机器报告中允许标记 collector unavailable。

### 6.2 确定性本地运行时

运行时应随 npm 包版本化安装，不依赖网络或 `postinstall`，使用 Node.js 20+ 标准库实现：

- 配置与状态校验；
- 原子 append/checkpoint；
- 字段白名单和 secret/path redaction；
- 反馈采样；
- 周/月汇总；
- 阈值检测；
- 保留与 dry-run cleanup；
- 标准 Git argv 同步；
- due/idempotency；
- proposal canonical JSON 与 SHA-256。

任何 shell 命令必须以 argv 执行，不拼接 shell 字符串。运行时必须可通过绝对路径调用，普通
记录不得依赖再次运行 `npx` 或访问 npm registry。

### 6.3 Maintainer Skill

`openapi-engineering-maintainer` 使用独立 `SKILL.md`，frontmatter 只含 `name` 与
`description`，正文低于 500 行；详细隐私、分析和 promotion 规则放在一跳可达的 references。

它只在以下请求触发：分析使用摘要、解释 trigger、生成私有改进候选、准备 promotion proposal、
或在精确批准后把候选移交正式 Contract-First 开发。普通 OpenAPI 项目决策不得触发它。

### 6.4 可选 launcher

launcher 用于严格样本，负责：

- 标记开始/结束和真实退出状态；
- 观测受控子进程树的 wall time 与峰值 RSS；
- 传入明确 agent、项目别名和 intent；
- 设置超时并在超限时终止自身启动的进程组；
- 不读取或导出目标项目内容。

launcher 不成为普通 Skill 的强制入口。

## 7. 数据契约与分类

所有数据使用 JSON Schema Draft 2020-12、`additionalProperties: false` 和显式 schema
版本。OpenAPI 控制面只通过外部 `$ref` 引用权威 Schema，不复制字段定义。

### 7.1 Usage Configuration

最低字段：

```yaml
config_version: 1
local_collection_enabled: false
sync_enabled: false
device_alias: null
coordinator: false
state_root: default
remote: null
branch: null
retention:
  local_days: 90
  remote_days: 365
feedback:
  successful_sample_every: 5
analysis:
  primary: codex
  secondary: claude
  max_events: 50
  timeout_seconds: 600
  warning_rss_mb: 512
  hard_rss_mb: 1024
schedule:
  due_check: daily
  period: iso-week
```

配置不得含 token、密码、私钥或内联认证头。Git 身份认证完全委托用户现有的 SSH/credential
机制。

### 7.2 Local Usage Event

本地事件可包含但不限于：

- session/event ID、设备别名、时间、Skill digest/version；
- platform、可观测 platform version、capture mode；
- 加盐项目 ID 与人工 project alias；
- lifecycle modes、tool decision、outcome；
- interview turns、boundary revisions、人工推翻标记；
- gate passed/failed/unverified 计数；
- duration/RSS 的值、单位和 availability；
- Completion Report 的结构化字段；
- feedback 状态和本地 incident 关联。

本地事件也不得包含原始对话、源码、spec 正文、命令 stdout/stderr、环境变量或凭据。实际命令
只允许存储命令类别或经过白名单归一化的程序名，不能存储可能包含路径/secret 的完整 argv。

### 7.3 Sanitized Usage Event

远端事件是重新构造的白名单对象，而不是对本地对象做字符串替换。必须删除：

- 绝对路径、用户名、home、主机名、远端 URL；
- 原始项目路径和本地盐；
- 任意自由文本 outcome、风险、命令或错误栈；
- 可能携带业务名、endpoint、schema 或 payload 的字段；
- secret-shaped value。

同步对象只保留分类枚举、计数、布尔值、时间桶、匿名 project ID、版本/digest 和已批准的短标签。

### 7.4 User Feedback

主观反馈必须独立于 AI assessment：

```yaml
rating: met | friction | wrong-decision | execution-error | skipped
friction_tags: []
note: null
feedback_status: answered | unknown | skipped
```

`note` 只保存在本地，除非用户单独确认其脱敏版本。AI不能把 `unknown` 改写成正面或负面评价。

### 7.5 Summary、Trigger、Analysis 与 Proposal

- Summary：周期、样本数、完成率、推翻率、unverified 率、问答统计、资源趋势、数据完整度。
- Trigger Finding：稳定 rule ID、阈值版本、输入 digest、observed value、threshold、severity。
- Maintenance Analysis：主分析器、平台/模型版本、输入 digest、聚类、置信度、候选原因、未验证项。
- Maintenance Proposal：候选 ID、契约影响、精确文件范围、失败测试计划、验证、资源、回滚、输入
  digests 和 approval SHA-256。

proposal digest 必须由 canonical JSON 计算；任何输入、候选、契约或目标文件 hash 变化都会使批准
失效。

## 8. 本地与私有仓库布局

POSIX 默认路径：

```text
~/.config/openapi-engineering-skill/usage.json
~/.local/state/openapi-engineering-skill/
├── local/events/<device>/<yyyy-mm>.jsonl
├── feedback/<device>/<yyyy-mm>.jsonl
├── outbound/<device>/
├── checkpoints/
├── summaries/
├── incidents/
└── locks/
```

Windows 使用用户本地配置/状态目录的等价位置；测试必须通过 `--home`/`--state-root` 隔离，不能
写真实 home。

私有 Git 工作树：

```text
events/<device>/<yyyy-mm>.jsonl
feedback/<device>/<yyyy-mm>.jsonl
summaries/<yyyy>/<iso-week>.json
findings/<yyyy>/<iso-week>.json
analyses/<yyyy>/<iso-week>/
proposals/<candidate-id>.json
promoted/<candidate-id>/
```

每台 collector 只能写自己的 events/feedback 分区；M4 可以写 summaries/findings/analyses/
proposals。远端内容始终是不可信输入，读取后必须重新做路径、schema、digest 和 secret 检查。

## 9. 反馈抽样

以下场景必须询问一次：

- outcome 为 partial/failed；
- 存在 failed 或 unverified gate；
- 用户推翻工具选择或要求重新定界；
- 发生安全、平台、同步或资源 finding；
- 用户主动调用 feedback。

普通成功按设备、按有效成功事件计数，每第 5 次询问一次，不使用随机数。反馈问题最多两步：先
选择 rating；只有非 `met`/`skipped` 时再选择一个主要 friction tag。用户不答时不得阻塞原任务，
记录 `unknown`。

## 10. 确定性触发规则

| Rule ID | 默认条件 | 动作 |
|---|---|---|
| `SI-SAFETY-001` | 任一未授权写入或安全越界 | 立即触发，P0 候选，要求 Claude 复核 |
| `SI-PLATFORM-001` | 同一可比较输入的 Codex/Claude 边界或策略漂移 1 次 | 立即复核 |
| `SI-FRICTION-001` | 同类 friction 30 天内至少 3 次 | 触发聚类 |
| `SI-OVERRIDE-001` | 至少 5 个可比较样本且工具选择推翻率 >20% | 审计决策规则 |
| `SI-UNVERIFIED-001` | 至少 5 个样本且 unverified 率 >20% | 审计验证能力 |
| `SI-INTERVIEW-001` | 问答轮数中位数 >5，或单次 >8 | 审计问题复用/去重 |
| `SI-RESOURCE-001` | 峰值 RSS >过去基线 2 倍或 >512 MB | 生成资源 finding |
| `SI-REGRESSION-001` | 已关闭 incident 再次匹配 | 立即作为 regression 触发 |

规则配置必须版本化。AI只能分析确定性脚本输出的 finding；人工可以随时手动创建 finding，但 AI
不能把未命中阈值的观察伪造成自动触发。

## 11. AI 分析治理

- 默认 Codex 主分析，输入最多 50 个脱敏事件/聚类摘要，超时 600 秒。
- 安全、平台漂移、P0/P1 候选、主分析低置信度或主分析 blocked 时，才串行调用 Claude Code。
- 主、备用分析器不得并发；Claude 不可用时标记 `review_status: blocked`，不得重复使用 Codex
  冒充独立复核。
- 自动 AI 只能读取脱敏 trigger bundle；不得读取本地详细事件、目标项目、原始对话或凭据。
- 认证默认使用显式批准的环境变量。没有 API key 时，可经本次运行显式选择
  `active-cli-session`：Codex 只把当前登录会话的最小凭据文件暂存到独立临时 `HOME`；Claude
  Code 只从权限安全的用户 settings 提取白名单内的 `ANTHROPIC_*` 认证、兼容端点和模型字段到
  受控子进程环境，不加载 hooks、plugins、permissions、MCP、历史、项目或 Agent 配置。使用
  DeepSeek/MiMo 等兼容端点时必须记录实际模型，不得冒充 Anthropic 模型证据。凭据不得进入
  prompt、模型输出或证据，临时 `HOME` 必须在分析器退出后删除。凭据缺失、符号链接、所有者
  不符、权限过宽或异常大小一律 blocked，不得回退到真实用户 `HOME`。
- 自动 AI 输出只写私有 analyses/candidates；其中的命令、路径和建议仍是不可信数据，不能执行。
- 自动分析只允许启动其自身受控子进程；禁止同时运行生成器、第二模型或其他付费任务。
- Claude Code 复核必须禁用全部 tools，允许最多 2 个内部 turn 完成结构化输出；达到上限仍未
  产出 Schema 合法结果时按 failed 处理，不得放宽工具或继续无界重试。
- 备用适配器已经启动但返回非零状态、无效 JSON 或无效结构化输出时必须记录为 `failed`，保留
  实际资源测量并输出固定枚举的无敏感 `failure_code`；只有未启动、认证/平台门禁或资源硬门禁才
  记录为 `blocked`。不得把已运行失败伪装成 `not-run` 或丢弃其峰值 RSS、耗时和进程组回收证据。
- 已有 Codex 主分析通过而 Claude 复核 blocked/failed 时，允许用 `--resume-analysis` 复用已校验
  的主分析；必须重算当前 bundle digest、finding IDs、既有分析 Schema 和 `analysis_id` 自一致性，
  任一漂移都在启动 Claude 前 blocked，且不得借 resume 跳过一个从未通过的 Codex 主分析。
- 子进程 watcher 默认在 512 MB 记录 warning，超过 1024 MB 或 600 秒时终止该受控进程树并
  生成 blocked/resource finding；不得终止用户已有 Codex/Claude/浏览器进程。

## 12. Git 同步与离线语义

- 使用显式 argv 调用 Git，并禁用仓库 hooks；不得执行仓库内脚本。
- `sync configure` 必须展示 remote、branch、允许路径和待同步数据分类，批准后才保存。
- 自动同步只处理 outbound 中已通过 schema/digest/secret scan 的文件。
- 网络、认证、non-fast-forward 或校验失败不得丢失本地事件，也不得阻塞原 Skill 完成。
- 每台机器只拥有自己的 append-only 分区；M4 聚合时读取所有分区但不改写 collector 历史。
- 不自动创建远端、不修改远端权限、不记录凭据；remote 是否私有由负责人确认。
- 合并冲突或不可信远端修改必须进入 blocked 状态，不能自动选择一方覆盖。

## 13. Retention、清理与撤销

- 本地事件和本地主观反馈默认 90 天；脱敏远端事件默认 365 天。
- 汇总、确认 incident、proposal 和 promoted eval 长期保留。
- cleanup 默认只生成按路径、数量、时间和 digest 的计划；必须 `--apply` 才删除。
- 配置改短保留期不能追溯触发删除；必须另行批准 cleanup 计划。
- promoted 或 legal-hold 标记对象不得被普通 cleanup 删除。
- `usage disable --apply` 停止新增记录但保留数据；清除数据是独立操作。
- 回滚安装/升级不得恢复旧授权或把已禁用采集重新启用。

## 14. CLI 控制面

计划支持以下平台无关命令；改变授权/配置/删除的命令默认 dry-run：

```text
openapi-engineering-skill usage status
openapi-engineering-skill usage enable [--device <alias>] [--apply]
openapi-engineering-skill usage disable [--apply]
openapi-engineering-skill usage sync configure --remote <url> --branch <branch> [--apply]
openapi-engineering-skill usage record --completion-report <path> --capture-mode <mode>
openapi-engineering-skill usage feedback --session <id> --rating <rating> [--tag <tag>]
openapi-engineering-skill usage summarize --period <iso-week|30d|90d>
openapi-engineering-skill usage sync
openapi-engineering-skill usage due
openapi-engineering-skill usage cleanup [--apply]
openapi-engineering-skill maintenance analyze --findings <path> \
  [--credential-mode <environment|active-cli-session>] [--resume-analysis <path>]
openapi-engineering-skill maintenance propose --analysis <path>
openapi-engineering-skill maintenance promote --proposal <path> --approve <sha256>
openapi-engineering-skill session run --agent <codex|claude> --project-alias <alias> -- <argv>
```

授权已启用后的普通 event append 和已批准 remote 的白名单同步不重复要求 `--apply`；授权边界、
目标或数据分类变化仍必须重新批准。所有命令提供 JSON 输出、稳定退出码和 `--home`/
`--state-root` 测试隔离参数。

## 15. Contract-First 要求

实现前必须将控制面 `info.version` 从 `1.1.0` 提升到 `1.2.0`，新增 Usage 与 Maintenance tags
及下列 operation 语义：

- usage configuration；
- usage event/feedback recording；
- sanitization and sync；
- summary and due checks；
- deterministic trigger findings；
- maintenance analysis/proposal；
- approval-bound promotion。

Usage、feedback、summary、trigger、analysis、proposal 和配置结构由独立 JSON Schema 成为唯一
权威。示例必须由真实确定性 CLI fixture 捕获，不手写一份漂移的输出。若实现发现契约缺口，先改
Schema/OpenAPI/示例和失败测试，再改实现。

## 16. 非功能要求

- **默认私密**：安装后零采集、零同步、零模型调用。
- **确定性**：相同输入/配置/周期产生相同 summary、finding 和 proposal digest。
- **原子性**：配置、checkpoint、summary、proposal 写入使用临时文件 + rename；中断不留半文件。
- **幂等性**：重复 record/session/period/sync 不产生重复事件或重复 AI 调用。
- **跨平台**：核心记录/脱敏/汇总/Git 在 macOS/Linux/Windows CI；P0 自动 scheduler 仅 macOS。
- **失败透明**：缺失字段为 `unavailable`，外部故障为 blocked，不将未运行步骤写成 passed。
- **低资源**：日常记录不得调用模型；确定性 due check 不读取大文件或完整 Git 历史。
- **可回滚**：授权、scheduler、maintainer 安装和 promotion 都有 dry-run 与精确回退范围。
- **渐进披露**：Maintainer `SKILL.md` 保持精简，详细策略放一跳 references，机械工作放脚本。
- **无隐式网络**：只有已批准 Git sync 和阈值触发 AI 可以联网；普通 record/summarize 离线可用。

## 17. 功能性验收标准

- **SI-AC-01**：全新安装、升级和普通 Skill 使用在未启用时不创建 usage 文件、不联网、不调用模型。
- **SI-AC-02**：本地采集与远端同步分别经过 dry-run 和 `--apply`；修改 remote/branch/设备别名
  会使旧同步授权失效。
- **SI-AC-03**：日常事件记录不含原始对话、源码、spec、stdout/stderr、完整 argv、环境变量或
  secret-shaped value。
- **SI-AC-04**：远端事件由白名单重建；绝对路径、用户名、主机名、remote URL、本地盐和自由文本
  均不能通过同步 schema。
- **SI-AC-05**：普通成功每第 5 次询问一次；失败、partial、unverified、override、安全/资源异常必问；
  未回答不阻塞任务且保持 unknown。
- **SI-AC-06**：best-effort 缺失指标记录 `unavailable`；launcher 样本记录真实退出码、耗时、RSS
  和 capture source。
- **SI-AC-07**：M2/MBP14 只能写各自事件分区，M4 才能写汇总/分析；M4 离线不会触发其他机器 AI。
- **SI-AC-08**：Git 网络/认证/冲突失败不丢本地记录、不覆盖远端、不阻塞原任务；远端 hooks 不执行。
- **SI-AC-09**：相同周期与输入 digest 重复 due 不重复 summary 或模型调用。
- **SI-AC-10**：平衡档八条规则按固定窗口/最小样本/阈值产生可复算 finding；未命中时模型调用为零。
- **SI-AC-11**：Codex 是默认主分析器；Claude 只在规定风险下串行复核；不可用时明确 blocked。
- **SI-AC-12**：自动 AI 输入只含脱敏 trigger bundle，最多 50 事件；不能读取目标项目或本地详细记录。
- **SI-AC-13**：受控 AI 超时、RSS 超限或异常退出会终止自身子进程树并生成 blocked evidence，
  不影响用户已有进程。
- **SI-AC-14**：自动产物只写私有分析区；源码、公开 Issue/分支/PR、npm 和目标项目保持零变化。
- **SI-AC-15**：proposal digest 绑定输入、Skill/配置版本、契约影响、文件 hash、测试、验证、资源和
  回滚；漂移或错误 digest 无法 promotion。
- **SI-AC-16**：本地 90 天、远端 365 天分层清理可复算且默认 dry-run；promoted/hold 对象不删除。
- **SI-AC-17**：Codex 与 Claude Code 安装同一运行 Skill；Maintainer 是独立 Skill 且通过结构、触发
  和一跳 reference 校验。
- **SI-AC-18**：P0 端到端 fixture 能证明 opt-in → record → redact → local Git sync → due → finding
  → fake/Codex analysis → private proposal，全程公开源码树 hash 不变。

## 18. 成功指标

按最近 30/90 天观察：

- 有效事件完整率和 `unavailable` 分布；
- 工具选择人工推翻率；
- interview 中位数和单次高值；
- boundary reapproval、failed/unverified 和重复 incident；
- Codex/Claude 可比较样本漂移；
- 日常 collector wall time 与峰值 RSS；
- finding → candidate → approved → regression test 的转化；
- 修复后同类 incident 的复发率。

调用次数、生成代码行数、AI 自评分不得单独作为成功标准。

## 19. 分期交付

### P0：端到端最小闭环

完成权威契约、显式 opt-in、本地事件、白名单脱敏、智能抽样、标准 Git 同步、due/summary、平衡
阈值、Codex 单分析、私有 candidate/proposal、M4 launchd 和端到端 fake/受控 Codex 验证。

### P1：可靠性与双平台加固

完成 Claude 风险复核、可选 launcher、精确 RSS/timeout、三机离线恢复、同步冲突/幂等、跨平台
核心测试、版本升级/安装体验和资源回归。

### P2：从候选到可复现改进

完成 approval-bound promoted eval、趋势/复发分析、维护 UX、真实双平台 forward eval、发布门禁与
证据保留优化。

## 20. 回滚原则

- 禁用采集只停止新事件，不隐式删除历史。
- scheduler 卸载只删除本系统创建且 digest 匹配的任务定义。
- Git sync 回滚只撤销本系统的未推送候选；已推送 append-only 历史不得重写。
- AI candidate 可删除或归档，但不能反向修改事实事件。
- promotion 失败必须保持公开源码不变；已批准实施由正式计划规定独立 Git/外部 snapshot 回滚。
- 发布后的 npm 版本不可覆盖；缺陷使用新版本、deprecate 和版本化迁移修复。

## 21. 尚待部署时提供的配置

以下不是需求开放问题，不阻塞开发：

- 私有 Git remote URL 与 branch；
- 三台机器最终设备别名；
- M4 launchd 具体本地运行时刻；
- 当前可用 Codex/Claude CLI 和模型版本。

这些值必须在 `usage enable`/`sync configure` 部署时显示并批准，不写死在仓库或 npm 包中。
