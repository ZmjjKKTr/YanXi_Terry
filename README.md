# 📞 言犀 — AI 智能通话管家

> 国家级大创项目 | v3.0 | 基于 RAG + 智谱 GLM 的智能来电代接系统
>
> 核心场景：用户上课/不便接听时，自动识别来电类型并给出代接、拦截、转接通知等处理。

---

## ✨ 核心功能

- **🧠 智能分类**：RAG 向量检索 + 关键词匹配 + LLM 增强，6 关 Pipeline 覆盖 4 大类来电
- **🤖 Agent 代接**：5 类 LLM Agent（外卖/快递/诈骗/重要多轮/通用），few-shot 示例驱动自然对话
- **📋 自动处理**：外卖快递自动引导放置点、诈骗电话直接拦截、重要来电 4 轮事务转达并通知机主
- **🎙️ 语音模式**：Vosk 离线语音识别 + Edge TTS 语音合成，无需联网
- **👤 用户画像**：per-user 课表、白名单、自动规则、紧急通知偏好，`--setup` 交互式配置
- **🔍 RAG 知识库**：500 条来电记录 → Chroma 向量库，L2 距离检索 + 关键词纠偏 + 反向校验
- **🛡️ 安全兜底**：28 个敏感词直接拦截 + 诈骗自动入库 + 换菜/退货等不代决定
- **📊 质检闭环**：通话质检 → 标记错误 → `--learn` 增量学习入库 → 向量库重建
- **🌐 REST API**：FastAPI 9 端点，Pydantic 类型校验，线程安全，支持并发

---

## 🚀 快速开始

### 1. 环境准备

```bash
git clone <your-repo-url>
cd yanxi-re0

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp key.env.example key.env
```

编辑 `key.env`，填入智谱 API Key（[获取地址](https://open.bigmodel.cn/)）：

```
ZHIPUAI_API_KEY=你的API_KEY
ZHIPU_MODEL=glm-4-flash
```

> 💡 仅使用 Ollama 本地模型时无需智谱 Key，修改 `LLM_BACKEND=ollama` 即可。

### 3. 首次运行

```bash
python main.py
```

首次启动自动构建 Chroma 向量库（约 1-2 分钟）。之后每次启动直接加载已有向量库。

---

## 🎤 使用方式

### 文本模拟（推荐入门）

```bash
python main.py              # 键盘输入来电内容，查看 AI 回复
python main.py --debug      # 调试模式，显示 RAG 分类过程
```

```
[call_001] 来电内容: 喂你的外卖到了给你放哪
>> 言犀回复: 放东门快递柜吧，谢谢！
```

### 语音模式

```bash
python main.py --voice      # 麦克风录音 → ASR 识别 → AI 回复 → TTS 播报
```

### 个人设置向导

```bash
python main.py --setup      # 交互式配置课表、收件位置、紧急联系人等
```

### REST API

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
# 访问 http://localhost:8000/docs 查看 Swagger 接口文档
```

| 端点 | 说明 |
|------|------|
| `POST /api/v1/calls` | 创建新通话 |
| `POST /api/v1/calls/{id}/turns` | 发送一轮对话 |
| `GET /api/v1/calls/{id}` | 查询通话摘要 |
| `POST /api/v1/calls/{id}/review` | 提交质检结果 |
| `GET/PUT /api/v1/users/{id}` | 用户画像 CRUD |
| `POST /api/v1/users/{id}/auto-rules` | 自动规则管理 |
| `POST /api/v1/knowledge/learn` | 知识库增量学习 |
| `GET /api/v1/stats` | 系统运行状态 |

---

## 📖 来电分类类型

| 来电类型 | 处理动作 | 处理规则 |
|----------|----------|----------|
| 外卖/快递 | 代接 | 上课时段自动引导放置点，周末按用户设置决定是否转接 |
| 外卖/快递（需决策） | 转接 | 换菜/退货/缺货/损坏等不代决定，引导对方 APP 留言通知机主 |
| 诈骗/推销 | 拦截 | 直接回复"不需要，谢谢。"，自动入库诈骗黑名单 |
| 重要来电（普通） | 事务转达 | 4 轮对话收集信息（身份→事由→补充→复述确认），结束通知机主 |
| 重要来电（紧急） | 优先通知 | 医院/急诊等命中关键词立刻通知机主，通话不挂断继续收集信息 |
| 普通来电 | 通用兜底 | 礼貌询问对方身份，告知稍后回电 |

---

## 🔄 全链路 Pipeline

```
来电输入
  ├─ Gate 0a: 自动拦截规则（用户学习的一律拦截词）
  ├─ Gate 0b: 来电白名单（known_callers 直接路由）
  ├─ Gate 0c: 自动放行规则（用户学习的一律放行词）
  ├─ Gate 0d: 自动通知规则
  ├─ Gate 1:  敏感词兜底拦截（28 个强敏感词）
  ├─ Gate 2:  RAG 向量检索 + 阈值过滤（score > 1.2 → 兜底）
  ├─ Gate 2.5: 关键词纠偏（外卖/重要信号词强制修正）
  ├─ Gate 2.6: 反向校验（无信号词则降级为普通来电）
  └─ Gate 3:  Agent 路由
       ├─ 外卖/快递 → 时间调度 + 决策检测
       ├─ 诈骗/推销 → "不需要，谢谢。"
       ├─ 重要来电 → 4 轮事务转达 + 紧急分级通知
       └─ 普通来电 → 通用礼貌回复
```

---

## 📁 项目结构

```
yanxi-re0/
├─ main.py                  # CLI 入口（文本/语音/质检/设置/增量学习）
├─ api.py                   # REST API（FastAPI 9 端点）
├─ pipeline.py              # 全链路编排器（6 关 + 线程安全）
├─ agents.py                # LLM Agent（5 类场景 + few-shot）
├─ knowledge_base.py        # RAG 知识库（Chroma + sentence-transformers）
├─ user_manager.py          # 用户画像管理（课表/白名单/自动规则）
├─ models.py                # Pydantic 数据结构
├─ config.py                # 全局配置
├─ test_full.py             # 全场景自动化测试（16 用例）
├─ speech/                  # 🎙️ 语音模块
│   ├─ asr.py               #   Vosk 离线语音识别
│   └─ tts.py               #   Edge TTS 语音合成
├─ docs/                    # 📖 项目文档
│   ├─ README.md            #   项目入口（本文件）
│   ├─ FEATURES.md          #   功能清单与实现状态
│   ├─ DEVLOG.md            #   版本变更记录
│   └─ ARCHITECTURE.md      #   设计决策与架构
├─ data/
│   ├─ 200条来电记录.txt     #   知识库数据（500 条）
│   └─ users/               #   per-user 画像/记录
├─ tests/                   #   测试报告
├─ requirements.txt
├─ key.env.example
└─ .gitignore
```

---

## 🧪 技术栈

| 类别 | 技术 | 用途 |
|------|------|------|
| LLM | 智谱 GLM-4-Flash / Ollama | 5 类 Agent 回复生成 |
| RAG | LangChain + Chroma | 500 条来电记录向量检索 |
| Embedding | sentence-transformers MiniLM | 中文文本向量化 |
| ASR | Vosk（离线） | 语音转文字 |
| TTS | Edge TTS | 文字转语音播报 |
| API | FastAPI + Pydantic v2 | REST 接口 + Swagger 文档 |
| 用户管理 | per-user JSON Profile | 课表/白名单/自动规则持久化 |

---

## 🔧 可用命令

```bash
# === 主入口 ===
python main.py                  # 文本模拟模式
python main.py --debug          # 调试模式（显示分类过程）
python main.py --voice          # 语音模式（麦克风 + TTS）
python main.py --user 用户名     # 切换用户

# === 设置与维护 ===
python main.py --setup          # 个人习惯设置向导
python main.py --rebuild        # 重建向量库（修改知识库后）
python main.py --review         # 通话质检（交互式 y/n/s）
python main.py --learn          # 增量学习（从质检修正样本入库）

# === API 服务 ===
uvicorn api:app --host 0.0.0.0 --port 8000

# === 测试 ===
python test_full.py             # 16 场景自动化测试
```

---

## ⚠️ 注意事项

- **API Key**：使用智谱 LLM 需配置 `ZHIPUAI_API_KEY`，纯 Ollama 本地模式可不配置
- **向量库**：首次运行自动构建（约 1-2 分钟），之后启动秒级加载
- **模型下载**：首次运行会自动下载 sentence-transformers MiniLM 模型（~500MB），请确保网络畅通
- **Vosk 模型**：语音模式需提前下载 Vosk 中文模型到 `../vosk-model-cn-0.22/`
- **知识库格式**：`data/200条来电记录.txt` 为 CSV 格式（编号,内容,分类,规则标签），支持手动追加后 `--rebuild`

---

## 📄 许可证

MIT 许可证
