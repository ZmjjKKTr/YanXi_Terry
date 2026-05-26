# 开发日志

> 用途：按时间倒序记录每个版本的改动内容，不重复 FEATURES 中的功能清单。

## v3.1 (2026-05-26) — GitHub 发布准备 + 项目整理

- 目录整理：文档移入 `docs/`，语音模块移入 `speech/`，根目录精简至 12 文件
- 新增 `.gitignore`（排除 key.env / chroma_db / __pycache__ / *.jsonl）
- 新增 `key.env.example` 环境变量模板（脱敏）
- 删除旧向量库目录 `chroma_db/` 和 `chroma_db_v2/`
- 删除旧 `.env.example`（含泄露 API Key）
- 重写 `docs/README.md`：采用 Hybrid RAG 风格，补充分类表/Pipeline 流程图/API 端点表
- 简化 `FEATURES.md` / `DEVLOG.md` / `ARCHITECTURE.md`，精简篇幅并标注每个文档的明确用途
- 清理 `data/users/` 下的运行时数据（calls.jsonl/scams.jsonl/review.jsonl）
- 清理孤立文件 `说明`
- 冒烟测试通过：关键词检测 + RAG 检索 + API 路由 + 文件一致性

## v3.0 (2026-05-20) — 知识库扩充 + 决策转接 + 事务转达流程

- 知识库 300→500 条（外卖 180/诈骗 170/重要 80/普通 70），向量库 chroma_db_v3
- 重要来电 4 阶段事务转达：收集→补充确认→复述确认→结束，全程"您"敬称，对话历史防遗忘
- 换菜/退货/缺货/损坏 → DECISION_NEEDED_SIGNAL 检测，不代决定，引导对方 APP 留言
- 周末转接逻辑完善：尊重 weekend_auto_accept，重要来电周末强制紧急通知

## v3.0 (2026-05-19) — 实时质检 + 自动规则 + 增量学习

- 通话结束自动分析（分类/置信度/RAG top-3/纠偏记录）→ 实时质检（y/n/s）→ 自动规则学习
- 3 个新 Gate：自动拦截(Gate 0c) → 自动放行(Gate 0d) → 自动通知(Gate 0e)
- `--learn` 增量学习：从 review.jsonl 提取修正样本，确认后入库 + 重建向量库
- 时间感知调度 + 紧急来电分级通知 + `--setup` 便捷设置向导
- `--review` 交互式质检完整实现：逐条展示低置信通话 + 统计面板

## v3.0 (2026-05-18) — 重要来电多轮对话

- agent_important_multiturn：三句话原则（寒暄确认→了解事由→留联系方式）
- escalation_agent：通话结束生成通知摘要
- SessionState 增强：important_stage/important_info 追踪多轮状态
- Pipeline 第 0 关前检查：重要来电进行中跳过 RAG 直接继续多轮

## v3.0 (2026-05-18) — 多用户基础设施

- 数据目录重构：data/users/{user_id}/ per-user 独立存储
- 来电白名单 known_callers + 诈骗自动入库 scams.jsonl
- `--user` 切换用户、`--review` 质检骨架

## v2.3 (2026-05-17) — 分类纠偏 + few-shot

- 关键词二级纠偏（_correct_category）、反向校验
- 三个 Agent 各加 few-shot 对话示例
- 通话日志 call_log.jsonl

## v2.2 (2026-05-17) — 知识库扩充 + Windows 兼容

- 知识库 200→300 条，Windows GBK 终端适配，Chroma 目录改为 chroma_db_v2

## v2.1 (2026-05-17) — 通话质检修复

- 每轮重检分类（修复"一次定终身"）、RAG 阈值生效、agent_delivery LLM 自行判断子场景

## v2.0 (2026-05-17) — 全模块拆分 + 双后端

- 7 模块拆分（config/knowledge_base/user_manager/agents/pipeline/asr/tts）
- 智谱 + Ollama 双后端，Chroma 向量库持久化

## v1.x (2026-03~05) — 早期原型

- v1.3: Vosk ASR + Edge TTS 语音模块
- v1.2: 用户画像 + 上课时段判断 + 自动代接
- v1.1: 智谱 GLM-4-Flash SDK + RAG + LLM 全链路
- v1.0: HuggingFace Embedding + Chroma 向量库
- v0.x: LangChain + Ollama/Qwen 实验
