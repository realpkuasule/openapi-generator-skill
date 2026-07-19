# OpenAPI Engineering 自我改进系统实施计划

> 状态：已批准设计，待实施
> 日期：2026-07-19
> 需求基线：`docs/openapi-engineering-self-improvement-requirements.md`
> 实施原则：Contract-First、Test-Driven、默认私密、dry-run-first、串行低资源

## 1. 目标与边界

实现个人自用的 `openapi-engineering` 使用信息闭环：在显式 opt-in 后自动记录客观事实，经过
白名单脱敏同步到平台无关的私有 Git remote，由 M4 周期性执行确定性汇总和阈值检测，必要时
串行调用 Codex/Claude 生成私有改进 proposal；任何公开源码改动仍需负责人批准精确 SHA-256。

本计划不授权：创建真实远端仓库、配置真实 SSH 凭据、修改 M2/MBP14、自动创建公开 Issue/PR、
发布 npm、读取真实项目内容、运行 OpenAPI Generator JAR，或在未展示单独边界时执行付费模型
forward test。

## 2. Contract-First 变更顺序

可观察行为发生变化，因此不能沿用 npm release 中的“no schema change”结论。实施必须先完成：

1. 将 `contracts/openapi-engineering.openapi.yaml` 的控制面版本从 `1.1.0` 提升到 `1.2.0`；
2. 新增 Usage/Maintenance operations、CLI 映射、退出码和权限语义；
3. 新增权威 JSON Schema 与捕获示例；
4. 先让契约/示例测试 RED，再实现运行时；
5. 将 `SI-AC-01`～`SI-AC-18` 绑定契约、测试与新鲜证据；
6. 任何实现期字段变化必须先修改 Schema/OpenAPI/示例测试，再修改代码。

计划中的行号均基于 `v0.1.0-rc.2` 合并提交 `08e1a6b`，新建文件从 `L1` 起；实现前若目标文件
漂移，必须重算行号和计划 digest。

## 3. TDD 执行纪律

每个任务使用固定循环：

```text
契约/验收定义
  → 最小失败测试
  → 记录 RED 退出码和失败原因
  → 最小实现
  → 目标测试 GREEN
  → 安全/回滚/跨平台反例
  → deterministic gate
```

- 测试只使用临时 home/state root、本地 bare Git remote、fake clock 和 fake AI adapter。
- 正常 CI 禁止网络、真实 home、真实 Git remote、Codex/Claude 模型和生成器 JAR。
- RED/GREEN 证据写入本次实现专属 `docs/verifications/self-improvement-20260719/`；原始大日志优先
  使用 CI artifact，仓库只保留最小可复算证据与最终报告。
- 测试失败时不得降低 Schema、跳过 secret scan、扩大允许路径或把 blocked 改写成 passed。

## 4. P0 — 端到端最小闭环

### P0-01 先定义 Usage/Maintenance 权威 Schema

- **文件路径与行号**：
  - `contracts/schemas/usage-config.schema.json:L1-L220`（新建）
  - `contracts/schemas/usage-event.schema.json:L1-L300`（新建，含 local/sanitized defs）
  - `contracts/schemas/user-feedback.schema.json:L1-L130`（新建）
  - `contracts/schemas/usage-summary.schema.json:L1-L240`（新建）
  - `contracts/schemas/maintenance-finding.schema.json:L1-L170`（新建）
  - `contracts/schemas/maintenance-analysis.schema.json:L1-L220`（新建）
  - `contracts/schemas/maintenance-proposal.schema.json:L1-L260`（新建）
  - `tests/test_usage_contracts.py:L1-L320`（新建，先写 RED）
- **具体改动**：
  - 使用 Draft 2020-12、`additionalProperties: false`、显式 schema version 和严格枚举；
  - 区分 local event 与 sanitized event，后者结构上不能容纳路径、自由文本、remote 和本地盐；
  - 为 measured/unavailable 指标定义 value/source/availability，不使用猜测值；
  - proposal 要求输入 digest、Skill/config 版本、契约影响、精确文件 hash、失败测试、验证、资源、
    回滚和 approval digest；
  - 为八条默认规则定义稳定 rule ID、最小样本、窗口、threshold 和 severity。
- **验证方法**：
  - `uv run python -m unittest tests.test_usage_contracts -v` 首次因 Schema 缺失为 RED；
  - 添加 Schema 后验证合法 fixture 通过，额外字段、路径、secret、unknown rating、无来源指标失败；
  - 两次 canonical proposal 产生相同 SHA-256，任一字段变化导致 digest 变化。

### P0-02 更新 OpenAPI 1.2.0 与捕获示例

- **文件路径与行号**：
  - `contracts/openapi-engineering.openapi.yaml:L1-L416`（版本、tags、paths）
  - `contracts/openapi-engineering.openapi.yaml:L417-L860`（components/external refs）
  - `contracts/examples/usage-status-response.json:L1-L40`（新建）
  - `contracts/examples/usage-record-response.json:L1-L55`（新建）
  - `contracts/examples/usage-summary-response.json:L1-L90`（新建）
  - `contracts/examples/maintenance-finding-response.json:L1-L70`（新建）
  - `contracts/examples/maintenance-proposal-response.json:L1-L100`（新建）
  - `tests/test_contracts.py:L16-L104`、`L196-L276`（先更新期望并观察 RED）
  - `scripts/capture_contract_examples.py:L14-L24`、`L200-L250`（后续接真实 fixture）
- **具体改动**：
  - `info.version` 升至 `1.2.0`，新增 `Usage`、`Maintenance` tags；
  - 添加 configuration、record/feedback、sanitize/sync、summary/due、finding、analysis/proposal 和
    approval-bound promotion operation；
  - 每个 operation 声明 `x-cli-command`、argv、稳定退出码、默认只读/standing opt-in/精确批准语义；
  - OpenAPI 只 `$ref` P0-01 Schema；示例最终由 CLI fixture 捕获，禁止手写字段分叉。
- **验证方法**：
  - `uv run python -m unittest tests.test_contracts -v` 先因版本/operation/schema/example 集合不匹配 RED；
  - `openapi-spec-validator`、全部本地 `$ref` 和示例 schema 验证 GREEN；
  - `uv run python scripts/capture_contract_examples.py --check` 必须能复算示例。

### P0-03 实现默认关闭的配置与本地状态根

- **文件路径与行号**：
  - `lib/usage/config.mjs:L1-L260`（新建）
  - `lib/usage/atomic-files.mjs:L1-L180`（新建）
  - `lib/usage/paths.mjs:L1-L170`（新建）
  - `bin/openapi-engineering-skill.mjs:L32-L95`（增加嵌套命令解析）
  - `bin/openapi-engineering-skill.mjs:L375-L397`（路由 usage commands）
  - `tests/test_usage_config.py:L1-L300`（新建，先写 RED）
- **具体改动**：
  - 实现 `usage status/enable/disable` 和 `usage sync configure`；所有授权/配置改变默认 dry-run，
    只有 `--apply` 原子写入；
  - POSIX 使用 `.config`/`.local/state`，Windows 使用等价用户本地目录；测试可用 `--home` 和
    `--state-root` 完全覆盖；
  - 新安装/升级不创建配置；禁用只停止新增数据，不删除历史；
  - remote/branch/device/state root/分类变化使同步授权失效，配置禁止 secret-shaped value。
- **验证方法**：
  - 初始 `status` 只读且 snapshot 不变；enable dry-run 零写入；apply 后只有批准路径变化；
  - 重复 apply 幂等；畸形/敏感配置退出 2 且不回显 canary；
  - Windows/macOS/Linux 临时 home 集成测试通过。

### P0-04 实现本地记录、脱敏与智能反馈抽样

- **文件路径与行号**：
  - `lib/usage/events.mjs:L1-L320`（新建）
  - `lib/usage/redact.mjs:L1-L300`（新建）
  - `lib/usage/feedback.mjs:L1-L220`（新建）
  - `lib/usage/canonical-json.mjs:L1-L130`（新建）
  - `tests/test_usage_recording.py:L1-L380`（新建，先写 RED）
  - `tests/test_usage_security.py:L1-L360`（新建，先写 RED）
- **具体改动**：
  - 实现 event ID、原子 append/checkpoint、重复 session 幂等和 local/sanitized 双对象；
  - sanitized 对象必须从白名单重建，项目 ID 用本地未同步盐；
  - 禁止原始对话、源码、spec、stdout/stderr、环境变量、完整 argv、绝对路径和自由文本进入远端；
  - 失败/partial/unverified/override/安全资源异常必问，普通成功按设备每第 5 次询问；
  - feedback 不回答时保持 unknown，不阻塞 Completion Report。
- **验证方法**：
  - 使用路径、用户名、API key、恶意 JSON、命令注入、Unicode 和 symlink fixture 先观察 RED；
  - secret/path canary 在 sanitized/outbound/stdout/stderr 中均为零；
  - 第 1～4、6～9 次成功不问，第 5/10 次问；异常事件每次问；
  - 同一 session 重放不增加行数，进程中断后 JSONL 仍可读取。

### P0-05 实现汇总与平衡档阈值

- **文件路径与行号**：
  - `lib/usage/summarize.mjs:L1-L340`（新建）
  - `lib/usage/thresholds.mjs:L1-L360`（新建）
  - `contracts/examples/usage-thresholds.valid.json:L1-L100`（新建）
  - `tests/test_usage_summary.py:L1-L360`（新建，先写 RED）
  - `tests/test_usage_thresholds.py:L1-L420`（新建，先写 RED）
- **具体改动**：
  - 以 fake clock 计算 30/90 天和 ISO week，输出样本完整度、override/unverified、interview、
    platform 和 resource 统计；
  - 精确实现 SI-SAFETY/PLATFORM/FRICTION/OVERRIDE/UNVERIFIED/INTERVIEW/RESOURCE/REGRESSION；
  - finding 绑定 rule/config/input digest；阈值未命中时必须产生空 findings，不触发模型；
  - 无测量值不得进入 RSS 基线，样本不足不得计算比率触发。
- **验证方法**：
  - 每条规则至少有 below/equal/above boundary 测试；20% 必须是严格大于，最小样本为 5；
  - 同一输入无论文件遍历顺序如何都产生相同 summary/finding digest；
  - `unknown` feedback 不当作正负评价；无 comparable key 不报告平台漂移。

### P0-06 实现平台无关私有 Git 同步

- **文件路径与行号**：
  - `lib/usage/git-sync.mjs:L1-L420`（新建）
  - `lib/usage/ownership.mjs:L1-L180`（新建）
  - `tests/test_usage_git_sync.py:L1-L460`（新建，先写 RED）
- **具体改动**：
  - 仅使用 argv 调用 Git，所有调用带 `core.hooksPath` 禁用值；不执行仓库脚本；
  - 测试使用临时 bare remote，验证每设备独占 events/feedback 分区与 M4 聚合路径；
  - 同步前复验 schema/digest/secret scan；网络/认证/non-fast-forward/冲突保留 outbound；
  - 不创建远端、不改权限/全局 Git 配置、不存凭据；remote 内容作为不可信输入。
- **验证方法**：
  - 本地 bare repo 完成 M2、MBP14、M4 顺序提交与拉取；无跨设备覆盖；
  - 恶意 symlink、path traversal、hook、篡改 digest、非所有者写入均 blocked；marker 不生成；
  - 失败重试不丢事件，成功重试不重复 commit/JSONL 行。

### P0-07 用官方 Skill 初始化器建立 Maintainer Skill

- **文件路径与行号**：
  - `skills/openapi-engineering-maintainer/SKILL.md:L1-L220`（新建）
  - `skills/openapi-engineering-maintainer/agents/openai.yaml:L1-L8`（新建）
  - `skills/openapi-engineering-maintainer/references/analysis-workflow.md:L1-L180`（新建）
  - `skills/openapi-engineering-maintainer/references/privacy-boundary.md:L1-L180`（新建）
  - `skills/openapi-engineering-maintainer/references/promotion-policy.md:L1-L200`（新建）
  - `tests/test_maintainer_skill.py:L1-L320`（新建，先写 RED）
- **具体改动**：
  - 先运行系统 `skill-creator/scripts/init_skill.py openapi-engineering-maintainer --path skills
    --resources references`，不得手工伪造初始化结果；
  - frontmatter description 覆盖 usage summary、trigger explanation、private candidate 和 approved
    promotion，排除普通 OpenAPI 任务；
  - 主流程只消费脱敏 finding bundle、生成私有分析/proposal、在精确批准前停止；
  - 详细策略一跳 references，Skill 目录不创建 README/CHANGELOG/安装指南。
- **验证方法**：
  - `quick_validate.py skills/openapi-engineering-maintainer`；
  - 测试 frontmatter 仅 name/description、正文 <500 行、一跳 references、无 TODO；
  - 触发/非触发 fixture 证明 Maintainer 不接管普通 OpenAPI 工程请求。

### P0-08 实现 Codex 主分析与私有 proposal

- **文件路径与行号**：
  - `scripts/maintenance/analyze_usage.py:L1-L380`（新建）
  - `scripts/maintenance/build_proposal.py:L1-L300`（新建）
  - `scripts/maintenance/adapters.py:L1-L260`（新建，复用现有 CLI protocol 的安全子集）
  - `tests/test_maintenance_analysis.py:L1-L420`（新建，先用 fake adapter RED）
  - `tests/test_maintenance_proposal.py:L1-L360`（新建，先写 RED）
- **具体改动**：
  - 自动分析入口只接受已校验 finding bundle，最多 50 事件，默认 Codex、600 秒；
  - 自动 AI 无目标项目路径和本地详细数据权限，使用隔离 home、只读模式和无写公共仓库策略；
  - 输出经 schema 验证后写私有 analysis/candidate，canonical proposal 绑定所有输入/文件 hash；
  - P0 正常 CI 使用 fake adapter；真实 Codex 仅作为获批的受控发布前验证，不进入普通测试。
- **验证方法**：
  - fake adapter 测试 passed/failed/blocked/malformed/timeout/extra-field；
  - 输入超过 50、含路径/secret、digest 过期、finding 未命中均在调用 adapter 前 blocked；
  - AI 输出中的命令/路径不执行；公共源码树前后 hash 相同；
  - 同一合法输入两次 proposal digest 相同，修改目标 hash 后旧 approval 失败。

### P0-09 实现 M4 due 与 macOS launchd dry-run-first 安装

- **文件路径与行号**：
  - `lib/usage/due.mjs:L1-L300`（新建）
  - `packaging/launchd/com.realpkuasule.openapi-engineering-maintainer.plist:L1-L90`（新建模板）
  - `lib/usage/launchd.mjs:L1-L260`（新建）
  - `tests/test_usage_due.py:L1-L320`（新建，先写 RED）
  - `tests/test_launchd_installation.py:L1-L300`（新建，先写 RED）
- **具体改动**：
  - 每日低成本检查配置/coordinator/period checkpoint；同 ISO 周/input digest 最多一次正式汇总；
  - M4 离线后补跑，collector 节点永不启动 AI；无 finding 时 adapter 调用计数必须为零；
  - schedule install/update/uninstall 默认 dry-run，apply 只修改本系统 digest 匹配的 plist；
  - plist 只启动 due command，不包含 token、remote 凭据或 shell 字符串。
- **验证方法**：
  - fake clock 覆盖当周重复、跨周、离线补跑、中断 checkpoint 和 collector 拒绝；
  - macOS 解析 plist 并验证 argv；Linux/Windows 返回 unsupported 而非写错误路径；
  - 卸载不删除用户同名但 digest 不匹配的任务定义。

### P0-10 集成原 Skill、npm 包与双组件安装

- **文件路径与行号**：
  - `skills/openapi-engineering/SKILL.md:L147-L149`（补充 opt-in completion hook，不增加分析职责）
  - `skills/openapi-engineering/references/platform-compatibility.md:L1-L35`（记录 collector fallback）
  - `package.json:L10-L25`（allowlist runtime、maintainer、packaging；扩展测试命令）
  - `bin/openapi-engineering-skill.mjs:L21-L30`、`L146-L214`、`L217-L359`（双组件 canonical/runtime）
  - `scripts/install_skill.py:L13-L18`、`L58-L164`、`L229-L253`（source fallback 双组件）
  - `tests/test_npm_distribution.py:L15-L215`（先更新期望并观察 RED）
  - `tests/test_skill_package.py:L12-L130`（保持运行 Skill 核心 references 不被 Maintainer 污染）
- **具体改动**：
  - npm canonical payload 同时包含 runtime、运行 Skill、Maintainer Skill；默认安装仍只启用运行 Skill；
  - M4 可显式选择 maintainer component，M2/MBP14 不必安装维护入口；
  - 普通 record 通过已安装绝对 runtime 调用，不再次访问 npm、不依赖 PATH/postinstall；
  - 安装/升级复制授权配置之前先检测，永不自动启用 usage/sync；
  - package 继续零运行时依赖和 allowlist 发布。
- **验证方法**：
  - 临时 home 执行 pack → install runtime only → enable → record → install maintainer → verify → uninstall；
  - 未启用安装/升级前后 state root 不存在；授权文件 hash 不被升级改写；
  - tarball 不含测试、私有事件、验证证据、缓存或开发凭据；
  - POSIX link/Windows copy 和冲突原子性测试 GREEN。

### P0-11 建立 SI 验收追踪与端到端门

- **文件路径与行号**：
  - `contracts/schemas/self-improvement-traceability.schema.json:L1-L220`（新建）
  - `contracts/self-improvement-acceptance-traceability.yaml:L1-L260`（新建，SI-AC-01～18）
  - `scripts/check_self_improvement_traceability.py:L1-L320`（新建）
  - `tests/test_self_improvement_traceability.py:L1-L300`（新建，先写 RED）
  - `tests/test_self_improvement_e2e.py:L1-L500`（新建）
  - `scripts/verify.py:L19-L28`、`L171-L245`（增加 Maintainer/Usage gates）
- **具体改动**：
  - 保留现有 AC-01～12 Schema/manifest 不变，SI 使用独立需求集避免伪造既有通过状态；
  - E2E 使用临时 home/state、本地 bare Git、fake clock/fake AI，覆盖完整 P0 链；
  - 结束时校验公开源码、真实 home 和 Agent 配置 hash 均未改变；
  - 新验证报告列出 configured/loaded/enforced/passing，blocked 不算 passed。
- **验证方法**：
  - traceability 在契约/测试/证据任一缺失时 RED；18 项全部绑定新鲜机器证据后 GREEN；
  - `uv run python scripts/verify.py --tier deterministic ...` 包含两个 Skill quick validation 和 usage E2E；
  - 本地 P0 最终全量单测、17 项既有门禁和新增门禁串行通过。

### P0 完成门

- OpenAPI 1.2.0、所有新 Schema、示例和 CLI 语义一致；
- 默认安装/升级零采集、零同步、零模型；
- 本地 opt-in 到私有 proposal 的 fake E2E 可复算；
- 未命中阈值时模型调用严格为零；
- Git/AI 失败不影响原任务或丢本地事件；
- Maintainer 与运行 Skill 职责、触发和安装组件无分叉；
- SI-AC-01～18 至少以 planned/static + 测试路径建立追踪，P0 范围项具备机器证据。

## 5. P1 — 双平台、launcher、多机恢复与资源加固

### P1-01 先写 Claude 风险复核契约与失败测试

- **文件路径与行号**：
  - `contracts/schemas/maintenance-analysis.schema.json:L1-L220`（增加 review 状态/独立平台字段）
  - `tests/test_maintenance_secondary_review.py:L1-L380`（新建，先写 RED）
  - `scripts/maintenance/adapters.py:L1-L260`（扩展 Claude adapter）
- **具体改动**：
  - 仅 safety/platform/P0/P1/low-confidence/primary-blocked 条件触发 Claude；
  - 强制平台、session、CLI version 不同且串行；不可用为 blocked，不能 Codex 重跑冒充；
  - 合并报告保留分歧，不以多数投票自动提升。
- **验证方法**：
  - fake 调用序列断言最大并发为 1；普通 finding 只调用 Codex；风险 finding 顺序 Codex→Claude；
  - Claude malformed/timeout/unavailable 均保留主分析和 blocked review。

### P1-02 实现可选严格 launcher 与资源 watcher

- **文件路径与行号**：
  - `lib/usage/session-launcher.mjs:L1-L420`（新建）
  - `lib/usage/process-watch.mjs:L1-L320`（新建）
  - `tests/test_usage_launcher.py:L1-L460`（新建，先写 RED）
  - `contracts/schemas/usage-event.schema.json:L1-L300`（收敛 measurement source）
- **具体改动**：
  - 只监控自身启动的进程组，记录 wall/exit/RSS；warning 512 MB，hard 1024 MB，timeout 600 秒；
  - 超限先优雅终止再强制终止子进程树，不触碰已有 Codex/Claude/浏览器；
  - capture mode/measurement source/unsupported 明确，best-effort 不能冒充 launcher。
- **验证方法**：
  - 小型内存/超时 fixture 验证 passed/warning/killed；marker 证明无旁路进程被终止；
  - Windows/macOS/Linux 可用能力分别报告，不可观测时 blocked/unavailable。

### P1-03 加固三机离线、同步冲突与恢复

- **文件路径与行号**：
  - `lib/usage/git-sync.mjs:L1-L420`
  - `lib/usage/due.mjs:L1-L300`
  - `tests/test_usage_multidevice.py:L1-L520`（新建，先写 RED）
- **具体改动**：
  - 覆盖 M2/MBP14 离线积累、M4 后补、重复 push、远端前进、部分周期和 checkpoint 恢复；
  - 每设备 ownership 与 M4-only 路径在每次同步复核；
  - 不实现自动协调权转移，配置错误明确 blocked。
- **验证方法**：
  - 三工作树 + bare remote 确定性集成；随机中断点重放后最终树一致；
  - 任何 collector 写 summaries/analyses 的尝试失败且远端不变。

### P1-04 完善 retention、撤销和 scheduler 生命周期

- **文件路径与行号**：
  - `lib/usage/retention.mjs:L1-L340`（新建）
  - `lib/usage/launchd.mjs:L1-L260`
  - `tests/test_usage_retention.py:L1-L420`（新建，先写 RED）
- **具体改动**：
  - 本地 90/远端 365 天，summary/incident/proposal/promoted 长期；
  - 配置改短不自动删，cleanup 单独 dry-run + apply，promotion/hold 不删；
  - disable/scheduler uninstall/upgrade 不恢复授权、不删除事实。
- **验证方法**：
  - fake clock 边界日前后、hold、symlink、篡改 digest、重复 apply；
  - scheduler 只删除自身 digest 匹配定义。

### P1-05 CI 与真实受控双平台验证

- **文件路径与行号**：
  - `.github/workflows/verify.yml:L3-L49`（确定性矩阵加入 Node usage gates）
  - `.github/workflows/verify.yml:L51-L85`（手动 Maintainer forward input/job）
  - `tests/test_ci_workflow.py:L14-L45`（先更新断言并观察 RED）
  - `scripts/verify.py:L171-L245`（新增 help/integrity gates）
- **具体改动**：
  - 普通 PR 只跑 fake/local Git，无网络模型；
  - 手动 self-hosted job 串行 Codex→必要时 Claude，带 environment approval；
  - artifact 保存原始运行证据，仓库只接收最终脱敏报告；
  - 记录峰值资源并验证无生成器/model 并发。
- **验证方法**：
  - Ubuntu/macOS/Windows deterministic 全绿；macOS launchd 专项；
  - 手动受控案例验证 Codex 主分析和一个风险 Claude 复核，公共源码树 hash 不变。

### P1 完成门

- 风险复核严格串行且触发条件可复算；
- launcher 资源/超时证据真实、不会杀用户进程；
- 三机离线/重放/冲突恢复不丢数据；
- retention 和 scheduler 可安全撤销；
- 普通 CI 零模型，手动双平台证据通过。

## 6. P2 — Promotion、趋势与发布收敛

### P2-01 先定义 approval-bound promoted eval

- **文件路径与行号**：
  - `contracts/openapi-engineering.openapi.yaml:L10-L416`（启用 promotion operation 完整语义）
  - `contracts/schemas/maintenance-proposal.schema.json:L1-L260`
  - `contracts/schemas/eval-case.schema.json:L1-L190`（仅在需要来源字段时向后兼容扩展）
  - `tests/test_maintenance_promotion.py:L1-L500`（新建，先写 RED）
  - `scripts/maintenance/promote_candidate.py:L1-L420`（新建）
- **具体改动**：
  - promotion 默认输出不可变计划，不写公开仓库；apply 要求精确 digest 与目标文件当前 hash；
  - 只允许把脱敏 fixture、eval、失败测试骨架和追踪候选写入批准路径；
  - 任一输入漂移、开放问题、secret 或额外路径导致全操作零写入。
- **验证方法**：
  - 错 digest、旧 hash、范围外路径、symlink、部分写故障均保持源码 snapshot 不变；
  - 正确 digest 原子写入后 eval Schema 通过且测试保持 RED，证明没有伪造修复。

### P2-02 实现趋势、复发与效果验证

- **文件路径与行号**：
  - `lib/usage/trends.mjs:L1-L360`（新建）
  - `lib/usage/regressions.mjs:L1-L300`（新建）
  - `tests/test_usage_trends.py:L1-L420`（新建，先写 RED）
- **具体改动**：
  - 比较 30/90 天窗口、修复前后事件和 incident fingerprint；
  - 样本不足只报告 insufficient，不宣称改善；
  - 已关闭问题复发触发 SI-REGRESSION-001，AI 自评分不计效果。
- **验证方法**：
  - fake timelines 覆盖改善/恶化/复发/样本不足/版本切换；
  - 输入顺序和设备到达顺序不影响输出 digest。

### P2-03 收敛文档、安装升级与发布契约

- **文件路径与行号**：
  - `README.md:L1-L90`（启用、隐私、M4/M2/MBP14 示例）
  - `CHANGELOG.md:L1-L30`（版本与 contract impact）
  - `package.json:L1-L46`（下一版本、allowlist、完整 prepublish gate）
  - `bin/openapi-engineering-skill.mjs:L1-L397`（status/upgrade 冲突提示和 component UX）
  - `docs/plans/self-improvement-20260719.md`（实施后回写实际行号与证据）
- **具体改动**：
  - 明确默认关闭、双重 opt-in、私有 remote 责任、disable/cleanup/rollback；
  - 修复 Git 旧版→npm/跨 npm 版本迁移时的 status/upgrade 体验；
  - npm 包保留零依赖/no postinstall，发布前跑完整确定性门而非仅 distribution tests；
  - 发布新版本，不覆盖已发布 RC。
- **验证方法**：
  - README 命令在临时 home 可复制；pack allowlist 和 registry tarball 生命周期通过；
  - prepublish 在契约/usage/maintainer 任一失败时阻止发布；
  - source/npm upgrade dry-run、apply、verify、rollback 全链通过。

### P2-04 最终双平台 eval 与 SI-AC 全追踪

- **文件路径与行号**：
  - `skills/openapi-engineering-maintainer/evals/*.yaml:L1`（新增正常、风险、隐私、漂移场景）
  - `contracts/self-improvement-acceptance-traceability.yaml:L1-L260`
  - `docs/verifications/self-improvement-20260719/final-report.json:L1`（生成）
  - `docs/verifications/self-improvement-20260719/gate-summary.md:L1`（生成）
- **具体改动**：
  - 使用最小脱敏 fixture 做 Codex/Claude forward test，不传预期答案；
  - 证明普通 OpenAPI 请求不触发 Maintainer，风险分析需要二次复核，promotion 等待 digest；
  - SI-AC-01～18 全部绑定当前 Skill/runtime/harness digest 的新鲜证据。
- **验证方法**：
  - 两平台每个关键场景至少 2 个新鲜样本，hard safety gate 全过；
  - 全量 deterministic、forward、security、resource、traceability 报告 passed 且 unverified 为空；
  - 公开源码、真实项目和 Agent 设置在未批准 promotion 场景保持不变。

### P2 完成门

- 私有 candidate 能在精确批准后安全生成 eval/失败测试骨架；
- 趋势结论有样本和版本证据，复发能自动识别；
- 安装、升级、发布、回滚文档与实际命令一致；
- SI-AC-01～18 全部具有新鲜机器证据；
- npm/GitHub 发布仍需负责人单独批准，不包含在本计划默认权限中。

## 7. 资源与安全硬门

- 所有模型调用串行；任意时刻最多一个受控 AI 子进程。
- 普通 record/redact/summarize/sync/CI 不调用模型或生成器。
- AI 输入最多 50 个 sanitized events，不读取本地详细数据或目标项目。
- 默认 timeout 600 秒、RSS warning 512 MB、受控子进程 hard limit 1024 MB。
- 网络只允许已批准 Git remote 与阈值触发的 AI CLI；缺少授权即 blocked。
- Git hooks 禁用；远端和 AI 输出均按不可信输入处理；不执行其中命令。
- 任何 canary 泄漏、未授权写入、用户进程终止、模型并发或真实 home 污染均为 P0 硬失败。

## 8. 回滚策略

- 每个写操作先 snapshot 目标 hash；原子 rename 失败时恢复已写目标。
- usage disable、sync disable、scheduler uninstall、cleanup 和 maintainer uninstall 分离，不能级联删数据。
- 私有 Git 历史 append-only；不得 force-push 或改写已同步事实。
- promotion 在完整 preflight 后才写，部分失败恢复全部本次目标。
- 安装器只删除自身管理且 digest 匹配的 Skill/runtime/plist；保留版本化 canonical payload。
- 已发布 npm 版本不可覆盖；缺陷发布新版本并提供 deprecate/rollback 指令。

## 9. 开发完成后的验证清单

### 实施回写（2026-07-19）

- P0 已完成：Contract-First Usage/Maintenance Schema、OpenAPI 1.2.0、默认关闭与双重授权、记录/脱敏/反馈/汇总/阈值、私有 Git 同步、Maintainer Skill、离线 E2E。
- P1 已完成：串行 Codex→风险 Claude 复核、真实 launcher/analyzer RSS 与 timeout、三设备聚合与重放、local/remote retention、launchd、普通 CI 零模型与手动 environment approval。
- P2 本地开发已完成：proposal Schema v2、精确摘要 promotion、原子回滚、趋势/复发、Maintainer eval、旧 Git/npm canonical 迁移、`0.1.0-rc.3` 发布准备。
- 最终本地证据：`docs/verifications/self-improvement-20260719/final-report.json` 为 26/26 passed；全量测试 260/260 passed；SI-AC-01～18 `acceptance_complete=true`；最近一次受监控全量验证峰值 RSS 110,100,480 bytes；0 swaps。
- 外部边界保持未执行：真实 Codex/Claude、跨平台托管 CI、Git push/PR/tag、GitHub release、npm publish 与真实三机 rc.3 安装；这些仍需负责人单独批准。

### Contract-First

- [ ] OpenAPI 控制面为 1.2.0，新增 operationId 唯一且 CLI 映射/退出码完整。
- [ ] 所有 Usage/Maintenance 结构只有一个权威 JSON Schema，OpenAPI 只用 `$ref`。
- [ ] 所有 Schema Draft 2020-12、拒绝额外字段，合法/非法 fixture 均有测试。
- [ ] 所有 response examples 可由确定性 fixture 重新捕获且 `--check` 无漂移。
- [ ] SI-AC-01～18 全部绑定契约、测试和新鲜证据。

### TDD 与确定性

- [ ] 每个 P0/P1/P2 任务有可核查 RED→GREEN 证据。
- [ ] fake clock、fake AI、临时 home/state、本地 bare Git 测试无网络可运行。
- [ ] 相同事件、周期、配置和 proposal 输入重复运行产生相同 digest。
- [ ] 重复 record/due/sync 不产生重复行、commit、summary 或模型调用。
- [ ] 既有 AC-01～12、158 项基线行为和 17 项 deterministic 语义无回归。

### 隐私与授权

- [ ] 全新安装、升级、普通使用默认零采集/同步/AI。
- [ ] local 与 sync 分别 dry-run + apply；授权边界变化使旧授权失效。
- [ ] sanitized/outbound/AI input 不含路径、用户名、主机名、remote、盐、自由文本或 secret。
- [ ] feedback unknown 不被 AI 解释成满意或不满意。
- [ ] 自动产物只写私有区；公开源码/Issue/分支/PR/npm/目标项目零变化。
- [ ] promotion 错 digest、漂移、范围外路径、symlink 和 partial failure 均零写入。

### 多机、Git 与调度

- [ ] M2、MBP14 只能写各自分区；M4-only 路径有确定性 ownership gate。
- [ ] M4 离线不转移 AI 权限，上线后能幂等补跑。
- [ ] Git hook/path traversal/篡改/冲突/non-fast-forward 不执行、不覆盖、不丢队列。
- [ ] 每日 due 低资源；同 ISO 周/input digest 最多一次正式分析。
- [ ] launchd install/update/uninstall dry-run-first，只管理 digest 匹配文件。

### AI 与资源

- [ ] 未命中阈值时 AI adapter 调用数严格为零。
- [ ] Codex 默认主分析；风险条件才串行 Claude，最大并发为 1。
- [ ] AI 输入不超过 50 events，只含 sanitized trigger bundle。
- [ ] timeout/RSS 超限只终止本系统子进程树，用户已有进程不受影响。
- [ ] Claude 不可用时 review blocked，不用 Codex 冒充第二平台。
- [ ] 运行模型/资源门时不并发运行生成器或第二模型。

### Retention、安装与发布

- [ ] 本地 90 天、远端 365 天和长期对象边界由 fake clock 验证。
- [ ] cleanup 默认 dry-run，promoted/hold 对象不删除。
- [ ] npm tarball 仅含 allowlist、零依赖、无 postinstall、无私有使用数据。
- [ ] Codex/Claude 共用运行 Skill；Maintainer 独立、<500 行、一跳 references。
- [ ] source/npm 安装、status、upgrade、verify、rollback 在 macOS/Linux/Windows 通过。
- [ ] 发布前全量门禁通过；真实 npm/GitHub 发布另行批准。

## 10. 实施结束时必须回写

完成后在本文件追加：

- 每个任务的实际文件与行号；
- RED/GREEN evidence 路径与 digest；
- OpenAPI 版本和 contract diff；
- 单测、deterministic、forward、security、resource、traceability 结果；
- M4/M2/MBP14 的实际部署状态；
- 未验证项、已知风险和精确回滚命令；
- 实际峰值 RSS、是否发生 swap 增长、是否遗留模型/生成器进程。
