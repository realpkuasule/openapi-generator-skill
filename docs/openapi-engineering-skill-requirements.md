# OpenAPI Engineering Skill 需求规格

> 状态：需求基线（待实现）  
> 日期：2026-07-14  
> 目标平台：Codex、Claude Code  
> 暂定 Skill 名称：`openapi-engineering`

## 1. 结论与立场

OpenAPI Generator 在当代工程中可以承担关键作用，但它不是应当“尽可能使用”的默认答案。

更准确的原则是：

- 应尽可能自动化维护**真正存在的跨进程、跨语言、跨团队或对外 HTTP 契约**；
- OpenAPI 是契约载体之一，OpenAPI Generator 是候选实现工具之一；
- 只有当生成物能够被稳定验证、重复生成且长期减少手写同步成本时，才采用代码生成；
- 当语言原生工具、厂商官方 SDK、契约治理工具更合适时，应选择它们；
- 当项目没有值得固化的 HTTP 边界，或生成成本高于收益时，应明确选择“不做代码生成”。

因此，本 Skill 不是 OpenAPI Generator 命令包装器，而是一个**项目感知、交互式授权、工具中立、覆盖全生命周期的 OpenAPI 工程决策与执行 Skill**。

## 2. 调研事实

### 2.1 官方能力与现实约束

- OpenAPI Generator 能从 OpenAPI 文档生成客户端、服务端桩、文档与配置，并提供 CLI、Maven、Gradle 和 CI/CD 集成。[OpenAPI Generator 官方仓库](https://github.com/OpenAPITools/openapi-generator)
- 截至 2026-07-14，最新稳定版为 `v7.23.0`；该版本仍明确包含带回退路径的 breaking changes，所以升级不能只做版本号替换，必须检查生成差异并重新编译、测试。[v7.23.0 release](https://github.com/OpenAPITools/openapi-generator/releases/tag/v7.23.0)
- 官方兼容性说明仍把 OpenAPI 3.1 支持标为 beta，而 OpenAPI 规范已经发布 3.2.0。这意味着“采用最新 OAS”与“获得目标生成器的可靠输出”不是同一件事。[OAG 兼容性](https://github.com/OpenAPITools/openapi-generator#overview)、[OpenAPI Specification](https://spec.openapis.org/oas/)
- 生成器成熟度和特性覆盖按目标不同而不同。例如 `typescript-fetch` 标为 stable，`python-fastapi` 标为 beta；即使 stable 生成器的官方特性表也存在未覆盖项，不能仅凭标签选型。[typescript-fetch](https://openapi-generator.tech/docs/generators/typescript-fetch/)、[python-fastapi](https://openapi-generator.tech/docs/generators/python-fastapi/)
- OpenAPI Generator 支持模板、配置、选择性生成和 `.openapi-generator-ignore`，但定制会形成需要维护的生成层，不能把模板分叉当作零成本能力。[Customization](https://openapi-generator.tech/docs/customization/)、[Configuration](https://openapi-generator.tech/docs/configuration/)

### 2.2 工程判断

OpenAPI Generator 价值最高的场景：

- 一个契约需要同时服务多个语言或多个消费者；
- 客户端、边界 DTO、服务接口存在大量机械同步工作；
- 生成输出可以在 CI 中完成 validate、generate、diff、compile/import 和 fixture/contract test；
- 团队能明确生成目录、手写扩展点、版本 pin、升级策略和契约所有权；
- 目标生成器对项目实际使用的 schema、鉴权、流式、文件上传、组合类型等特性经过实证验证。

不应默认采用的场景：

- 单体或 CLI 内部调用，不存在自有 HTTP 服务边界；
- 只对接少数第三方 API，而厂商官方 SDK 质量更高、更新更及时；
- 生成器对关键特性支持不足，需大量模板分叉或生成后补丁；
- 生成代码比手写薄适配层更复杂，且只有一个消费者；
- 契约真源实际是语言类型、框架路由或独立 JSON Schema，强行复制到 OpenAPI 会形成双重权威；
- 团队没有可执行的再生成和兼容性门禁。

## 3. 用户确认的核心要求

1. Skill 必须同时兼容 Codex 和 Claude Code。
2. Skill 支持全生命周期，但每次调用只启用当前意图所需的模式。
3. Skill 在识别项目后，必须先进行若干轮自适应交互式问答，确定工作边界。
4. 在边界获得明确批准之前，只允许只读识别、分析和必要的只读官方资料核验；不得安装依赖、修改文件、生成代码、启动有副作用的服务或改动 CI。
5. Skill 必须先给出“工作边界摘要”，等待用户确认后才能执行。
6. 执行中若范围扩大，必须暂停并重新确认新增边界。
7. Skill 有权选择官方 OpenAPI Generator、语言原生生成器、厂商官方 SDK、契约治理工具、MCP/Agent 接口生成工具，或明确决定不做代码生成。
8. Skill 必须把已确认的项目决策持久化为可版本控制的治理档案；后续调用复用已确认内容，只追问未知、变化或冲突项。

## 4. 目标与非目标

### 4.1 目标

- 判断项目是否需要 OpenAPI、是否需要代码生成，以及需要哪种生成。
- 识别项目阶段、契约真源、边界、消费者、语言、框架、构建系统和现有治理。
- 通过问答形成清晰、可审计的执行授权。
- 安全地配置、运行、验证和升级所选工具。
- 维护契约演进、破坏性变更、漂移、生成差异和退役决策。
- 对 Codex 和 Claude Code 提供一致的核心行为。

### 4.2 非目标

- 不鼓励为了“类型安全”而给所有项目引入 OpenAPI。
- 不把 OpenAPI Generator 固定为默认或唯一生成器。
- 不把生成的 DTO 自动提升为领域模型真源。
- 不在未确认边界时自动安装 Java、Node、Docker、CLI、插件或 MCP。
- 不自动执行生产 API 的写操作或破坏性契约测试。
- 不替代领域架构、协议设计、安全评审或厂商 SDK 的官方支持策略。

## 5. 运行模型：强制交互式边界协议

Skill 必须实现以下状态机：

```text
只读识别
  → 意图与阶段判断
  → 自适应多轮问答
  → 工作边界摘要（proposed）
  → 用户明确批准（approved）
  → 执行
  → 验证与结果报告
  → 持久化决策与证据
```

### 5.1 只读识别

允许：

- 读取仓库规则、README、架构文档、PRD、构建清单和锁文件；
- 查找 OpenAPI/Swagger、JSON Schema、生成配置、生成目录、CI 和历史决策；
- 查看 Git 状态、最近相关历史和已安装工具版本；
- 对当前版本、生成器状态和官方 SDK 做只读官方资料核验；
- 把发现与推断分开标记，并给出证据路径。

禁止：

- 修改或新建项目文件；
- 安装、升级或卸载依赖；
- 运行生成器、格式化器或可能改写文件的构建命令；
- 启动会访问真实外部 API、产生费用或改变数据的服务；
- 修改 Git、CI、编辑器或全局 Agent 配置。

### 5.2 自适应多轮问答

问答不得机械地一次抛出完整清单。每轮围绕一个决策簇，优先提供 2–4 个根据项目识别结果生成的选项，并说明影响。默认顺序：

1. **本次意图**：评估、首次接入、日常变更、审计、升级、排障、治理或退役；
2. **契约边界**：哪些 HTTP/进程边界在范围内，哪些明确不在；
3. **真源与消费者**：spec-first、code-first、hybrid、第三方契约；消费者及语言；
4. **生成范围**：客户端、服务端边界、类型、文档、mock、测试、MCP，或不生成；
5. **所有权**：哪些模型由 OpenAPI 拥有，哪些由领域 Schema/语言类型/厂商 SDK 拥有；
6. **执行权限**：允许修改的文件、依赖、CI、网络访问、服务启动和测试环境；
7. **验收门禁**：lint、breaking diff、compile/import、fixture、contract test、生成 diff；
8. **提交策略**：生成物是否入库、生成目录、手改禁令和升级窗口。

已由项目文件明确回答且没有冲突的问题不重复询问。推断会影响架构或写入范围时，必须让用户确认，不能静默采用。

### 5.3 工作边界摘要

执行前必须展示并等待明确批准：

```yaml
intent: 本次启用的生命周期模式
goals: 本次目标
non_goals: 明确不做的事项
contract_authority: 契约真源与模型所有权
boundaries: 在范围内的 API/进程/消费者
tool_decision: 候选、选择、拒绝理由、置信度
files_to_read: 关键输入
files_to_change: 精确路径或目录
dependencies: 允许新增/升级/不变
commands: 将运行的生成、验证、测试类别
network_and_external_effects: 网络、费用、真实服务风险
deliverables: 预期产物
acceptance_gates: 完成条件
rollback: 回退方式
open_questions: 必须为零或被显式接受
```

“继续”“可以”“按这个做”可视为对紧邻边界摘要的批准。模糊讨论、仅回答某个问题或批准部分选项，不构成整体执行授权。

### 5.4 需要重新确认的范围扩张

- 新增未批准的输出目录或修改已有手写代码；
- 改变契约真源或模型所有权；
- 从客户端生成扩大到服务端生成、mock、MCP 或 CI；
- 新增/升级依赖或切换生成器；
- 引入自定义模板、生成后补丁或 generator fork；
- 需要访问真实外部服务、凭据、付费 API 或执行写操作；
- 发现破坏性变更，需要迁移、版本升级或消费者联动；
- 验收标准需要降低或跳过。

## 6. 生命周期模式

一次调用可以组合必要模式，但必须在边界摘要中逐项列出。

| 模式 | 典型意图 | 主要产物 |
|---|---|---|
| Assess & Select | 是否需要 OpenAPI/代码生成，选什么工具 | 决策记录、候选比较、no-codegen 结论 |
| Initial Design | 设计新边界、真源和契约所有权 | 边界图、契约策略、初始规范计划 |
| First Integration | 首次接入生成与治理链 | 固定版本配置、生成目录、验证脚本、CI 门禁 |
| Daily Evolution | 增删改 endpoint/schema | 兼容性判定、生成 diff、消费者影响 |
| Audit & Drift | 审计 spec、实现、生成物和 CI 漂移 | 漂移报告、优先级和修复建议 |
| Upgrade & Migration | 升级 OAG/OAS/模板/目标框架 | 临时生成对比、迁移计划、回退点 |
| Troubleshoot | 生成失败、编译失败、类型异常 | 最小复现、根因、最小修复 |
| Governance Hardening | 建立 lint、diff、contract test、ownership | 规则、门禁、责任边界 |
| Reselect & Decommission | 更换生成器或停止生成 | 替代方案、清理计划、兼容证明 |

## 7. 工具选择决策引擎

### 7.1 候选类别

| 类别 | 优先场景 | 典型风险 |
|---|---|---|
| 官方 OpenAPI Generator | 多语言、多消费者、目标生成器实测成熟 | 输出庞大、模板漂移、目标支持不均、升级 diff 大 |
| 语言原生生成器 | 单一语言/框架，希望贴合生态与更小输出 | 跨语言一致性较弱，工具更分散 |
| 厂商官方 SDK | 第三方 API，厂商维护 SDK 且契约/鉴权复杂 | 受厂商版本策略约束，可能缺少所需平台 |
| 契约治理工具 | 只需 lint、breaking diff、mock、contract test | 不消除客户端手写同步成本 |
| MCP/Agent 接口工具 | 目标是让 Agent 调用已有 OpenAPI API | 不解决应用代码生成和契约治理全生命周期 |
| 不做代码生成 | 没有自有 HTTP 边界、单消费者、薄适配足够 | 仍需明确手写类型与测试的维护责任 |

### 7.2 必评维度

- 项目阶段：原型、首版、稳定期、迁移期、维护期；
- API 性质：自有/第三方、内部/公开、同步/流式、稳定/实验；
- 消费者数量与语言数量；
- 契约真源与模型所有权；
- OAS 版本和实际使用特性；
- 目标生成器状态、近版本 breaking change 和维护活跃度；
- 代表性契约能否生成、编译/import、通过 fixture 和 contract test；
- 生成代码大小、可读性、运行时依赖与安全面；
- 自定义模板和补丁的长期维护成本；
- 生成物是否入库及其 review/diff 成本；
- 官方 SDK 的质量、授权、版本和支持窗口；
- 团队已有工具、构建系统、CI 和技能；
- 退役和回退成本。

### 7.3 强制实证门

选择生成器不能只依据 README、星数或 stable/beta 标签。获批执行后，Skill 应使用覆盖项目关键特性的最小代表性契约，在临时目录完成：

1. 规范 validation/lint；
2. 固定版本生成；
3. 输出清单和生成差异；
4. 目标语言 compile/import；
5. 关键序列化、鉴权、错误、组合类型、文件/流式语义 fixture；
6. 判断需要的模板覆盖或薄适配层；
7. 给出采用、降级或拒绝结论。

临时试验也必须包含在批准的命令与网络边界中。

## 8. 项目治理档案

默认建议路径：`.openapi-engineering/profile.yaml`。若项目已有 `contracts/`、ADR 或治理目录，问答后遵循现有约定。

最低字段：

```yaml
profile_version: 1
project:
  kind: desktop-app | service | cli | library | monorepo | other
  stage: prototype | initial | active | stable | migration | maintenance
intent_history: []
contract:
  approach: spec-first | code-first | hybrid | third-party | none
  sources_of_truth: []
  ownership_rules: []
  openapi_version: null
boundaries: []
consumers: []
decision:
  strategy: openapi-generator | language-native | official-sdk | governance-only | mcp | no-codegen
  tools: []
  rejected_options: []
  rationale: []
generation:
  version_pins: []
  config_files: []
  output_directories: []
  generated_files_committed: null
  manual_edit_policy: null
validation:
  gates: []
  representative_fixtures: []
permissions:
  approved_write_scope: []
  approved_external_effects: []
evidence:
  verified_at: null
  source_urls: []
  observed_commands: []
```

规则：

- 记录“选择什么”也记录“为什么不选其他方案”；
- 固定工具版本、配置和可复现命令，不写模糊的 `latest`；
- 把事实、用户决策和 Skill 推断分别标记；
- 不持久化密钥、token、真实凭据或敏感 payload；
- 后续调用先读取档案并检测与当前仓库的冲突；
- 任何会改变所有权、工具类别或安全边界的档案更新都需要重新确认。

## 9. Codex 与 Claude Code 双平台设计

### 9.1 单一核心包

核心行为只维护一份，建议结构：

```text
openapi-engineering/
├── SKILL.md
├── agents/
│   └── openai.yaml              # Codex 展示与调用元数据
├── references/
│   ├── boundary-interview.md
│   ├── lifecycle-modes.md
│   ├── decision-framework.md
│   ├── generator-evaluation.md
│   ├── governance-gates.md
│   └── platform-compatibility.md
├── scripts/
│   ├── inspect_project.py
│   ├── validate_profile.py
│   └── compare_generation.py
└── evals/
    ├── animator.yaml
    ├── revoice.yaml
    └── scope-expansion.yaml
```

### 9.2 可移植性约束

- `SKILL.md` frontmatter 只依赖双方共同支持的基础字段；平台专属元数据放到适配文件。
- 核心流程不能依赖某个平台独有的问答 UI；有结构化选择器时使用，没有时以普通对话逐轮询问并等待。
- 核心流程不能依赖某个平台独有的 MCP；MCP 只能作为可选增强，并必须有 CLI/文件读取回退。
- 脚本接口保持平台无关，以标准输入/输出、明确退出码和 JSON 结果工作。
- 安装时可复制或链接同一核心目录到 Codex 与 Claude Code 的 Skill 目录；不得维护两份行为分叉的 `SKILL.md`。
- 必须分别在 Codex 与 Claude Code 执行相同 eval，比较问答顺序、授权门、工具决策和文件边界。

## 10. 现有 Skill / MCP 调研与复用结论

截至 2026-07-14，没有发现一个现成项目同时满足：双平台、只读识别、强制多轮边界问答、批准后执行、全生命周期、工具中立、允许 no-codegen、决策持久化。

本次通过 Firecrawl、GitHub 全局代码检索和候选仓库实际 `SKILL.md`/README 核验完成调研，没有安装或执行候选仓库代码。下列主要仓库在核验时均未归档且近期仍有提交；大部分仓库元数据为 MIT，OpenAPI Generator 为 Apache-2.0，`review-api-design` 文件单独声明 CC-BY-4.0。直接复用前仍应以目标文件和依赖的实际许可证为准。

| 候选 | 可复用价值 | 关键缺口 |
|---|---|---|
| [Factoria Powers: openapi-generator](https://github.com/juankmvanegas/factoria-powers/blob/master/skills/openapi-generator/SKILL.md) | 有 endpoint interview、批准后保存、版本历史和 breaking change 双重确认，是最接近交互授权的候选 | 面向特定 factory；主要是新项目与 spec 生成；固定 OpenAPI 3.1；不做工具选型、no-codegen、完整生命周期和通用项目档案 |
| [A5C Babysitter: openapi-generator](https://github.com/a5c-ai/babysitter/blob/main/library/specializations/software-architecture/skills/openapi-generator/SKILL.md) | 覆盖 spec 生成、validation、breaking diff、mock 和代码生成 | 没有强制边界问答/批准状态机；工具与命令偏模板化；不负责工具中立选择和持久化治理 |
| [Claude Dev Suite: openapi-generator](https://github.com/claude-dev-suite/claude-dev-suite/blob/main/skills/api-integration/openapi-generator/SKILL.md) | OAG 快速参考；知道 TypeScript 简单场景可改用 `openapi-typescript` | 主要是固定命令手册；无项目阶段判断、批准协议、全生命周期和档案；Claude 命名但未证明 Codex 行为一致 |
| [Spring Boot Skills: openapi-first](https://github.com/rrezartprebreza/spring-boot-skills/blob/main/skills/spring-boot-4/openapi-first/SKILL.md) | Spring delegate、生成目录和 Maven 配置参考 | 仅 Spring/OAG recipe；没有选择和治理闭环 |
| [REST API Design Review](https://github.com/psenger/ai-agent-skills/blob/main/skills/review-api-design/SKILL.md) | 自适应补问、规划期 API 评审、严重性与 readiness 输出 | 只评审，不配置/生成/演进；没有执行授权和工具决策 |
| [API Contract Skill](https://github.com/Lusinhas/pi-config/blob/main/skills/api/contract/skill.md) | 消费者识别、breaking diff、handler 对照和 contract test 思路 | 不是生成器选择 Skill；没有批准后才写入的强制状态机；未提供双平台包 |
| [PactFlow Agent Skills](https://github.com/pactflow/pactflow-agent-skills) | Drift、BDCT、Pact 与契约测试可作为治理模式的可选执行器 | 聚焦契约测试/PactFlow，不负责生成器选择、代码生成和项目全生命周期 |
| [Agentify](https://github.com/MonadWorks/agentify) | 从 OpenAPI 生成 MCP、Skills、`CLAUDE.md`、`AGENTS.md` 等 Agent 接口 | 目标是 Agent interface compiler；项目自称早期；不处理应用代码生成策略与治理决策 |
| [mcp-openapi-proxy](https://github.com/rendis/mcp-openapi-proxy) | 同时说明 Claude Code/Codex 配置；运行时以少量 navigator tools 暴露大型 API；明确 no-codegen | 是运行时 API→MCP 代理，不是工程决策 Skill |
| [OpenAPI MCP Server](https://github.com/ivo-toby/mcp-openapi-server) | 动态把 OpenAPI endpoints 暴露为 MCP tools，支持 stdio/HTTP 和过滤 | 解决 Agent 调用，不解决契约/代码生成全生命周期 |
| [API Design Reviewer / MCP Server Builder](https://github.com/alirezarezvani/claude-skills) | lint、breaking detection、scorecard、OpenAPI→MCP scaffold，可作为独立模式参考 | 是两个分离的局部 Skill；没有统一的项目决策、授权和持久化闭环 |

复用策略：参考其工作流和验收思路，必要时把外部工具作为可选执行器；不直接拼接多个 Skill 形成隐式流程，因为那无法保证统一授权门、相同项目档案和双平台一致性。引入任何第三方代码前，仍需单独完成许可证、依赖和安全审查。

## 11. 两个项目的验收场景

### 11.1 Animator Master Plan

输入：[2026-07-10-ai-motion-video-editor-master-plan.md](/Users/zhichao/Documents/animator/docs/superpowers/specs/2026-07-10-ai-motion-video-editor-master-plan.md)

Skill 应识别：

- Electron/React/Python 多进程桌面系统，有多个真实跨进程边界；
- 项目明确采用 contract-first；OpenAPI 拥有 endpoint/envelope/protocol，Draft 2020-12 JSON Schema 拥有领域 payload；
- 计划固定 OAG `v7.23.0`、OpenAPI 3.0.x、`typescript-fetch` 和可丢弃 Python 服务边界壳；
- CI 期望 validate → 临时 generate → diff → TypeScript compile/Python import → fixture；
- 厂商 AI API 应使用官方 SDK，而不是从厂商 OpenAPI 重新生成。

Skill 不得直接开始配置。至少应确认：

- 本次是评审 P0 方案、做最小生成 spike，还是正式落地；
- 哪些边界进入首轮，哪些领域 Schema 投影已有或需要生成；
- Python FastAPI beta 生成器失败时，是否只比较 Flask，还是也允许语言原生薄边界；
- 生成物是否入库、允许修改哪些目录和 CI；
- 是否允许安装/下载 OAG 7.23.0 及相关依赖。

预期决策不是“全部用 OAG”，而是：

- TypeScript 客户端：OAG 是强候选，需用项目关键 schema fixture 实证；
- Python 服务边界：把 OAG FastAPI 当可替换壳，只有 compile/import/contract gates 通过才采用；
- 领域文档：保持 standalone JSON Schema 真源，不复制成双重权威；
- 厂商 API：优先官方 SDK；
- SSE/复杂流式：允许一层经过测试的薄适配器。

### 11.2 Revoice PRD

输入：[PRD.md](/Users/zhichao/claude/revoice/docs/PRD.md)

Skill 应识别：

- Python 跨平台单体 CLI；
- 主要调用讯飞、QWEN、MiniMax 第三方 ASR/TTS API；
- PRD 没有自有 HTTP 服务或多语言消费者；
- 当前核心风险是厂商适配、重试、fallback、限流、费用、媒体处理和可测试性，而不是客户端/服务端类型同步。

默认建议应为 `no-codegen` 或 `official-sdk`，而不是引入 OAG。只有当用户计划建立自有服务边界、厂商没有可用官方 SDK且提供高质量稳定 OpenAPI、或多个消费者需要统一客户端时，才进入生成器评估。

验收点：Skill 必须能明确输出“本项目当前不应采用 OpenAPI Generator”，并给出较小的替代方案，而不是为了展示能力创建 OpenAPI 文件。

### 11.3 范围扩张场景

用户最初只批准审计；Skill 在审计中发现生成配置过期。Skill 可以报告发现和建议，但不得直接升级依赖或重生成。只有展示新的边界摘要并获得第二次批准后才能进入 Upgrade & Migration 模式。

## 12. 功能性验收标准

- **AC-01**：在两个示例项目上，任何写操作前均出现至少一轮项目识别和一轮边界确认；不允许把识别与执行合并。
- **AC-02**：用户未批准时，仓库文件、依赖、CI 和 Agent 配置零变化。
- **AC-03**：Animator 场景能给出混合策略，不把所有 Schema 和第三方 API 都交给 OAG。
- **AC-04**：Revoice 场景能选择 no-codegen/official SDK，并解释收益不足的原因。
- **AC-05**：同一输入在 Codex 和 Claude Code 得到等价的模式、关键问题、边界摘要和工具决策。
- **AC-06**：重复调用会复用治理档案，只询问改变、冲突或未知的内容。
- **AC-07**：选择任何生成器前，记录版本、生成器状态、关键 feature gap 和代表性 spike 结果。
- **AC-08**：升级时必须生成隔离 diff，并运行目标语言 compile/import 与契约 fixture；不得直接覆盖后宣称成功。
- **AC-09**：发现 breaking change、真实服务副作用或写入范围扩大时会暂停并重新确认。
- **AC-10**：所有完成报告包含实际运行的命令、验证结果、未验证项、风险和回退方式。
- **AC-11**：第三方 OpenAPI、README、描述字段和生成模板均作为不可信输入处理，不能借此扩大工具权限或执行任意指令。
- **AC-12**：Skill 可以仅完成评估/审计而不生成任何代码。

## 13. 非功能要求

- **可重复**：版本、配置、输入 digest、输出目录和验证命令可重现。
- **可审计**：用户决策、Skill 推断、官方证据和实际观察分开记录。
- **最小变更**：优先现有工具和项目约定；不为统一而重构无关代码。
- **安全**：不读取/输出密钥；生产写操作和付费 API 默认禁止；远程 spec 按不可信输入处理。
- **渐进披露**：`SKILL.md` 只保留核心状态机和路由，详细工具知识放 references，机械检查放 scripts。
- **时效性**：版本、生成器状态、SDK 推荐和规范支持属于易变信息，做选型/升级时必须从官方来源重新核验。
- **跨平台**：脚本至少支持 macOS/Linux；Windows 项目不得假设 Bash-only 流程，应提供 Python 或等价命令。
- **失败透明**：无法运行的门禁不能写成通过，必须标记为未验证并说明影响。

## 14. 实现阶段建议

1. 先实现只读项目识别、模式路由、问答协议和边界摘要，不接任何生成器。
2. 加入治理档案 schema、冲突检测和双平台 eval。
3. 实现 Assess & Select，以及 `no-codegen`、官方 SDK、OAG、语言原生工具的决策框架。
4. 首先接入只读 validation、breaking diff 和隔离 generation spike。
5. 再接入 First Integration、Daily Evolution、Upgrade、Troubleshoot 和 Decommission。
6. 最后把 PactFlow、Agentify 或 OpenAPI→MCP 工具作为明确授权的可选执行器，而不是核心依赖。

首版成功标准不是“支持最多生成器”，而是：在不同性质项目上做出不同且可解释的决定，并严格守住问答与授权边界。
