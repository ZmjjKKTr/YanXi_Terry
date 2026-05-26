# 言犀 — AI 智能通话管家

> 国家级大创项目 | v3.0 | 2026-05-20
>
> 自动识别来电类型，代接外卖/快递、拦截诈骗、重要来电转接通知。
> 提供 CLI 文本/语音模式和 REST API 两种使用方式。

## 快速开始

```bash
cd "E:\VS code\yanxi-re0"

# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp key.env.example key.env
# 编辑 key.env，填入智谱 API Key（https://open.bigmodel.cn/）

# 3. 运行
python main.py              # 文本模拟模式
python main.py --setup      # 个人习惯设置向导（推荐新用户先跑）
python main.py --voice      # 语音模式（麦克风 + TTS）
python main.py --review     # 通话质检
python main.py --debug      # 调试模式

# 4. API 模式
uvicorn api:app --host 0.0.0.0 --port 8000
# 访问 http://localhost:8000/docs 查看接口文档
```

## 测试

```bash
python test_full.py          # 16 个场景自动化测试
```

## 项目结构

```
yanxi-re0/
├─ main.py              CLI 入口（文本/语音/质检/设置/增量学习）
├─ api.py               REST API（FastAPI，9 个端点）
├─ pipeline.py          全链路编排器（6 关）
├─ agents.py            LLM Agent（5 类场景）
├─ knowledge_base.py    RAG 知识库
├─ user_manager.py      用户画像管理
├─ models.py            Pydantic 数据结构
├─ config.py            全局配置
├─ test_full.py         全场景自动化测试
├─ requirements.txt     Python 依赖
├─ key.env.example      环境变量模板
├─ speech/              asr.py + tts.py
├─ docs/                项目文档
├─ data/                知识库 + per-user 数据
└─ tests/               测试报告
```

## 文档索引

| 文件 | 用途 |
|------|------|
| `docs/README.md` | 项目入口，快速了解 + 启动 |
| `docs/FEATURES.md` | 功能清单与实现状态 |
| `docs/DEVLOG.md` | 版本变更记录 |
| `docs/ARCHITECTURE.md` | 设计决策与架构说明 |

## 全链路流程

```
来电输入
  ├─ 第0关：自动规则（拦截/放行/通知）+ 来电白名单
  ├─ 第1关：敏感词兜底拦截（28 个关键词）
  ├─ 第2关：RAG 向量检索 + 阈值过滤
  ├─ 第2.5关：关键词纠偏（外卖/重要信号词强制修正）
  ├─ 第2.6关：反向校验（无信号词则降级为普通来电）
  └─ 第3关：Agent 路由
       ├─ 外卖/快递 → 时间感知调度（上课代接/周末转接）
       ├─ 诈骗/推销 → "不需要，谢谢。"
       ├─ 重要来电 → 4 轮事务转达 + 紧急通知机主
       └─ 普通来电 → 通用礼貌回复
```

## 技术栈

- **LLM**: 智谱 GLM-4-Flash（主）/ Ollama（本地备选）
- **RAG**: LangChain + Chroma + sentence-transformers
- **ASR/TTS**: Vosk 离线识别 + Edge TTS
- **API**: FastAPI + Pydantic v2 + Uvicorn
- **知识库**: 500 条来电记录，4 分类（外卖/快递/诈骗/重要/普通）
