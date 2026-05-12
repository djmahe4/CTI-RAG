# ThreatRAG 一期稳上线可用性增强设计

## 1. 背景与目标

ThreatRAG 当前已经具备 Redis 会话缓存、RabbitMQ 原型 worker、多模型接入能力，但主聊天链路仍以 API 进程内同步检索与同步模型调用为主，模型选择逻辑也停留在静态选择阶段。现状可以满足开发和单机验证，但不适合直接面向生产流量，主要问题如下：

- API 进程直接承受检索和模型生成压力，远端模型抖动时会放大超时与失败。
- 模型调用没有统一的健康状态、熔断窗口、降级链和共享状态。
- Redis 仅承担会话缓存，尚未承担多实例共享控制面的职责。
- RabbitMQ 已有实验性实现，但还没有承担明确的一期生产职责。

一期目标是“稳上线”，不是“大重构”。本期仅增强可用性与可运维性，不改变前端交互协议和主流式接口形态。

## 2. 非目标

以下内容明确不纳入一期范围：

- 不将 `/chat/stream` 全量改造成“API 入队、worker 流式回传”的全异步架构。
- 不引入新的编排系统或服务发现组件。
- 不重写 `retriever`、`HistoryManager`、MySQL 会话结构等核心业务逻辑。
- 不做跨地域、多机房、高等级容灾设计。
- 不在一期内修改前端交互协议或引入新的流式事件格式。

## 3. 一期总体方案

一期采用“混合稳上线版”：

- 保留 `/chat/stream`、`/chat/temporary` 等主聊天接口的同步流式输出模式。
- 新增统一模型路由执行层，负责模型选择、超时、轻量重试、熔断、半开探测、回退与降级。
- Redis 从会话缓存升级为运行时共享控制面，保存模型健康状态、熔断状态、幂等键、短期缓存和异步任务状态。
- RabbitMQ 在一期只承接非强实时或高成本任务，例如异步检索、健康探测、缓存预热、延迟重试等。
- 对所有新行为提供环境变量开关，确保上线后可通过配置快速止损。

该方案的核心原则是：在不破坏现有主链路交互体验的前提下，把最不稳定的因素收口到独立的运行时层中。

## 4. 架构分层

### 4.1 API 层

API 层继续承接用户请求、鉴权、历史消息读写、流式响应输出，但不再直接承担“如何选模型”和“坏模型如何规避”的决策。

### 4.2 模型路由层

新增统一模型路由层，作为所有聊天模型调用的唯一入口。业务代码提交“期望模型”和“允许降级策略”，路由层返回实际执行结果与路由元信息。

### 4.3 Redis 运行时层

Redis 继续保存会话信息，同时增加运行时状态读写能力，用于多实例之间共享模型状态、熔断状态和任务状态。

### 4.4 RabbitMQ 任务层

RabbitMQ 不接管一期的流式 token 回传，只承接后台任务和削峰场景，避免主链路复杂度过快上升。

## 5. 模型路由、熔断与降级设计

### 5.1 路由入口

新增统一模型路由执行器，例如 `packages/models/router.py`。所有原本直接调用 `select_model(...).predict(...)` 的地方，改为先经过路由执行器。

### 5.2 主路由与回退链

每次请求可指定期望模型；如果未指定，则使用默认模型。路由器会根据配置生成候选链，例如：

- `deepseek:deepseek-chat`
- `ollama:qwen3:30b`
- `ollama:qwen2.5:7b`

路由器优先尝试主模型；如主模型不可用或命中熔断，则按顺序尝试下一个候选模型。

### 5.3 错误分类

以下错误记为“可用性失败”，参与熔断统计：

- 网络连接失败
- 请求超时
- 429 限流
- 上游 5xx
- 流式响应中途异常断开

以下错误不参与熔断：

- 模型名不存在
- 鉴权配置缺失
- 请求参数错误
- 业务逻辑错误

### 5.4 熔断状态机

每个模型维护独立状态：

- `closed`：正常可选
- `open`：短时间内禁止路由到该模型
- `half-open`：冷却结束后允许少量探测请求

建议规则：

- 在 60 秒窗口内累计 5 次可归因失败则进入 `open`
- `open` 持续 120 秒
- 冷却结束后进入 `half-open`
- `half-open` 仅允许 2 个探测请求
- 探测成功则恢复 `closed`
- 探测失败则重新进入 `open`

### 5.5 重试与降级

同一模型内只允许 1 次轻量重试，避免在坏模型上反复消耗时间。若仍失败，则进入下一候选模型。

降级分为两层：

- 同能力降级：优先切到可替代的在线模型
- 保底降级：当在线模型不可用时，退到本地 Ollama 模型

一旦某个模型已经成功开始流式输出，不允许在中途切换到另一模型，以避免前端接收到拼接错误的流。

### 5.6 响应元信息

响应 `meta` 中补充如下字段：

- `expected_model_provider`
- `expected_model_name`
- `actual_model_provider`
- `actual_model_name`
- `degraded`
- `route_reason`
- `request_id`

## 6. Redis 与 RabbitMQ 的职责边界

### 6.1 Redis 职责

Redis 在一期中承担以下职责：

- 会话缓存
- 模型健康状态
- 熔断窗口与失败计数
- 幂等键
- 短 TTL 结果缓存
- 异步任务状态

Redis 适合做“共享控制面”，因为它低延迟、读写简单、便于多 API 实例共享状态。

### 6.2 RabbitMQ 职责

RabbitMQ 在一期只承担后台任务与削峰：

- 异步检索任务
- 模型健康探测任务
- 缓存预热任务
- 外部依赖失败后的延迟重试任务

RabbitMQ 不用于一期的主流式 token 回传，以避免引入过高的时序复杂度。

### 6.3 主链路数据流

`/chat/stream` 一期数据流如下：

1. API 接收请求，生成 `request_id`
2. 读取 Redis 中的幂等键、模型状态和可选短缓存
3. 执行同步检索逻辑
4. 模型调用统一经过路由执行器
5. 路由执行器在调用过程中更新 Redis 熔断与健康状态
6. API 将结果保存到 MySQL 与 Redis 会话层
7. API 继续以现有协议向前端流式返回

### 6.4 异步任务数据流

异步任务流程如下：

1. API 或后台逻辑创建任务消息并发送到 RabbitMQ
2. worker 消费消息并执行任务
3. worker 将任务状态更新为 `queued / running / succeeded / failed / expired`
4. worker 将结果摘要写入 Redis
5. API 通过状态接口或后台检查结果

## 7. 模块边界与文件落点

### 7.1 新增模块

- `packages/models/router.py`
  - 统一模型路由入口
  - 承担超时、重试、熔断、降级
- `packages/models/router_types.py`
  - 存放路由配置与返回结构
- `rag/cache/redis_runtime.py`
  - 专门管理运行时状态，不与会话缓存混用
- `rag/mq/task_publisher.py`
  - API 侧统一发消息入口
- `rag/mq/task_worker.py`
  - 承担异步检索、健康探测、缓存预热等任务
- `rag/config/runtime_config.py`
  - 统一读取一期新增环境变量

### 7.2 修改模块

- `packages/models/__init__.py`
  - 保留底层模型构造能力
  - 增加面向路由层的统一入口
- `packages/models/chat_model.py`
  - 统一异常分类与超时包装
- `rag/api/routers/chat_api.py`
  - 所有聊天模型调用改走路由执行器
  - 补充响应路由元信息
- `rag/mq/rabbitmq_manager.py`
  - 增加交换机、重试队列、死信队列、消息 TTL、发布确认
- `worker.py`
  - 改为面向任务类型的统一 worker 启动逻辑
- `.env.example`
  - 补充一期相关配置项
- `docker-compose.yml`
  - 新增 `rabbitmq` 服务以及健康检查与依赖关系

### 7.3 暂不修改模块

- `packages/core/retriever.py` 主体检索算法
- `packages/core/history.py`
- MySQL 会话数据表结构
- 前端已有流式消费协议

## 8. 错误处理、重试与死信设计

### 8.1 路由层错误处理

路由层只对可重试错误执行轻量重试，最多 1 次。若仍失败，优先切换到回退模型，而不是继续在主模型上重复等待。

### 8.2 MQ 错误处理

MQ 任务处理采用分层重试：

- 首次失败：投递到重试队列
- 延迟后再次消费
- 超过最大重试次数：进入死信队列

### 8.3 队列规划

建议使用以下资源：

- `task.exchange`
- `task.queue`
- `task.retry.queue`
- `task.dlq`

死信消息中至少保留：

- `task_type`
- `request_id`
- `payload_digest`
- `error_type`
- `error_message`
- `retry_count`
- `failed_at`

## 9. 观测与日志设计

### 9.1 指标

一期至少需要采集以下指标：

- 每模型请求数
- 每模型成功率
- 每模型 P95 / P99 延迟
- 熔断打开次数
- 降级触发次数
- `/chat/stream` 首 token 延迟
- `/chat/stream` 完整响应耗时
- MQ 入队数、消费数、重试数、死信数
- MQ 队列积压
- Redis 短缓存命中率
- Redis 幂等命中率

### 9.2 日志

所有请求必须带 `request_id`。模型路由日志至少能回答以下问题：

- 原始期望模型是谁
- 实际命中了谁
- 为什么切换
- 失败归因是什么

日志中不得输出完整敏感内容和 API Key。

## 10. 配置设计

### 10.1 模型路由

建议新增环境变量：

- `MODEL_ROUTER_ENABLED=true`
- `MODEL_ROUTER_DEFAULT_PROVIDER=deepseek`
- `MODEL_ROUTER_DEFAULT_MODEL=deepseek-chat`
- `MODEL_ROUTER_FALLBACK_CHAIN=deepseek:deepseek-chat,ollama:qwen3:30b,ollama:qwen2.5:7b`
- `MODEL_ROUTER_REQUEST_TIMEOUT_SECONDS=45`
- `MODEL_ROUTER_STREAM_TIMEOUT_SECONDS=90`
- `MODEL_ROUTER_MAX_RETRIES_PER_MODEL=1`

### 10.2 熔断器

- `MODEL_CIRCUIT_BREAKER_ENABLED=true`
- `MODEL_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5`
- `MODEL_CIRCUIT_BREAKER_FAILURE_WINDOW_SECONDS=60`
- `MODEL_CIRCUIT_BREAKER_OPEN_SECONDS=120`
- `MODEL_CIRCUIT_BREAKER_HALF_OPEN_PROBES=2`

### 10.3 Redis 运行时状态

- `RUNTIME_REDIS_PREFIX=threatrag:runtime`
- `MODEL_STATUS_TTL_SECONDS=600`
- `REQUEST_IDEMPOTENCY_TTL_SECONDS=300`
- `SHORT_CACHE_TTL_SECONDS=120`

### 10.4 RabbitMQ

- `RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/`
- `RABBITMQ_TASK_EXCHANGE=threatrag.tasks`
- `RABBITMQ_TASK_QUEUE=threatrag.tasks.main`
- `RABBITMQ_RETRY_QUEUE=threatrag.tasks.retry`
- `RABBITMQ_DLQ=threatrag.tasks.dlq`
- `RABBITMQ_MAX_RETRIES=3`
- `RABBITMQ_RETRY_DELAY_MS=10000`

这些配置默认偏保守，目标是先稳再快。

## 11. 测试策略

### 11.1 单元测试

需要覆盖以下核心场景：

- 主模型成功
- 主模型失败后回退
- 熔断打开
- 半开恢复
- 不可重试错误不触发熔断
- Redis 状态读写与 TTL
- MQ 重试与死信流转

### 11.2 集成测试

使用 `docker-compose` 启动：

- MySQL
- Redis
- RabbitMQ
- API
- worker

验证以下能力：

- `/chat/stream` 在主模型可用时行为不变
- 主模型超时或限流时自动切换回退模型
- Redis 中可观察到模型状态变化
- 异步任务状态能从 `queued` 正常流转到结束态

### 11.3 故障注入

验证以下异常情况下系统是否降级可用：

- 远端模型不可达
- RabbitMQ worker 下线
- Redis 短时不可用

目标不是所有功能都正常，而是主链路仍能以可预期方式降级。

## 12. 上线步骤

### 12.1 本地验证

- 完成单元测试和集成测试
- 确认配置项可被正确读取
- 确认路由日志和 Redis 状态符合预期

### 12.2 预发验证

在接近生产的配置下验证：

- 首 token 延迟
- 完整响应时长
- 降级触发率
- 5xx 比例
- MQ 积压与死信数量

### 12.3 生产灰度

建议按以下顺序上线：

1. 部署 Redis runtime、RabbitMQ、worker 与新代码
2. 初始配置：
   - `MODEL_ROUTER_ENABLED=false`
   - `MODEL_CIRCUIT_BREAKER_ENABLED=false`
3. 验证基础连通性后，开启模型路由
4. 观察无异常后，再开启熔断
5. 按 5% -> 20% -> 50% -> 100% 放量

### 12.4 回滚

最快回滚手段是关闭配置开关，而不是立即回滚代码：

- `MODEL_ROUTER_ENABLED=false`
- `MODEL_CIRCUIT_BREAKER_ENABLED=false`

如果 MQ 路径异常，同步主链路仍可继续承载核心服务。

## 13. 风险与权衡

一期主要风险在于：

- 路由层接入点多，替换不彻底会导致部分调用绕过熔断与降级
- RabbitMQ 当前实现偏原型化，需要补足可靠性能力
- Redis 新承担运行时状态后，需要谨慎设计 key 前缀和 TTL，避免污染现有会话数据

对应权衡如下：

- 不重写主流式链路，降低首版联调风险
- 先让 RabbitMQ 承接后台任务，而不是直接承接 token 流
- 通过开关控制功能启用顺序，确保生产可回滚

## 14. 后续演进方向

如果一期稳定上线并验证收益，二期可继续推进：

- 将 `/chat/stream` 逐步迁移为“API 入队 + worker 执行 + 流式回传”
- 引入更细粒度的模型健康探测与自动恢复策略
- 为不同请求类型建立差异化模型路由策略
- 增加更完整的监控面板与告警规则

一期完成的标准不是“架构最先进”，而是“在当前项目结构下，生产可用性明显提升，且上线风险可控”。
