"""
言犀 REST API — FastAPI 应用
启动: uvicorn api:app --host 0.0.0.0 --port 8000
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Callable

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import API_KEY, API_HOST, API_PORT, DEBUG, set_user, get_user_review_path
from pipeline import get_pipeline
from user_manager import (
    get_user_profile, save_user_profile, add_auto_rule, get_auto_rules,
)
from models import (
    NewCallRequest, NewCallResponse,
    TurnRequest, TurnResponse,
    CallSummary,
    ReviewRequest, ReviewResponse,
    UserProfileResponse, UserProfileUpdate,
    LearnRequest, LearnResponse,
    StatsResponse,
    AutoRuleRequest, AutoRuleResponse,
)

app = FastAPI(
    title="言犀 AI 智能通话管家",
    description="REST API for AI call handling: classification, reply generation, review, and learning",
    version="3.1",
)

# ── CORS ──────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 鉴权 ──────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Depends(_api_key_header)):
    if API_KEY and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


RequireAuth: Callable = Depends(verify_api_key) if API_KEY else Depends(lambda: True)

# ── 启动事件 ──────────────────────────────────────

@app.on_event("startup")
def startup():
    get_pipeline()  # 预热 Pipeline（加载知识库 + 恢复会话）
    print(f"  言犀 API 已启动: http://{API_HOST}:{API_PORT}")
    print(f"  接口文档: http://{API_HOST}:{API_PORT}/docs")


# ══════════════════════════════════════════════════════
# 通话
# ══════════════════════════════════════════════════════

@app.post("/api/v1/calls", response_model=NewCallResponse, dependencies=[RequireAuth])
def create_call(req: NewCallRequest):
    """创建新通话，返回 session_id"""
    set_user(req.user_id)
    pipeline = get_pipeline()
    sid = pipeline.new_session(req.user_id)
    return NewCallResponse(session_id=sid)


@app.post("/api/v1/calls/{session_id}/turns", response_model=TurnResponse, dependencies=[RequireAuth])
def process_turn(session_id: str, req: TurnRequest):
    """发送一轮对话，返回 AI 回复 + 分类元数据"""
    pipeline = get_pipeline()
    # 从 session state 推断 user_id（优先用 session 中的）
    with pipeline._lock:
        state = pipeline._sessions.get(session_id)
        user_id = state.user_id if state else "zmjjkk"

    set_user(user_id)
    result = pipeline.process_structured(session_id, req.text, user_id)
    return TurnResponse(**result)


@app.get("/api/v1/calls/{session_id}", response_model=CallSummary, dependencies=[RequireAuth])
def get_call(session_id: str):
    """查询通话状态/摘要"""
    pipeline = get_pipeline()
    summary = pipeline.get_call_summary(session_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")
    return CallSummary(**summary)


# ══════════════════════════════════════════════════════
# 质检
# ══════════════════════════════════════════════════════

@app.post("/api/v1/calls/{session_id}/review", response_model=ReviewResponse, dependencies=[RequireAuth])
def submit_review(session_id: str, req: ReviewRequest):
    """提交质检结果"""
    pipeline = get_pipeline()
    summary = pipeline.get_call_summary(session_id)
    if summary is None:
        # 尝试从 _call_summaries 获取未 pop 的
        with pipeline._lock:
            summary = pipeline._call_summaries.get(session_id)

    if summary is None:
        raise HTTPException(status_code=404, detail="会话不存在或已过期")

    review_entry = {
        "time": datetime.now().isoformat(),
        "session": session_id,
        "input": summary.get("all_inputs", [""])[0] if summary.get("all_inputs") else "",
        "category": summary.get("category", ""),
        "rule": summary.get("rule", ""),
        "response": "",
        "review_time": datetime.now().isoformat(),
    }

    if req.review == "correct":
        review_entry["review"] = "correct"
        message = "已标记为正确"
    else:
        review_entry["review"] = "wrong"
        review_entry["correct_category"] = req.correct_category or "未指定"
        message = f"已标记为错误，正确分类: {req.correct_category}"

    try:
        # 推断 user_id
        with pipeline._lock:
            state = pipeline._sessions.get(session_id)
            user_id = state.user_id if state else "zmjjkk"
        review_path = get_user_review_path(user_id)
        with open(review_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(review_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return ReviewResponse(ok=True, message=message)


# ══════════════════════════════════════════════════════
# 用户画像
# ══════════════════════════════════════════════════════

@app.get("/api/v1/users/{user_id}", response_model=UserProfileResponse, dependencies=[RequireAuth])
def get_user(user_id: str):
    """查询用户画像"""
    profile = get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在，请先运行 --setup")
    return UserProfileResponse(user_id=user_id, profile=profile)


@app.put("/api/v1/users/{user_id}", response_model=UserProfileResponse, dependencies=[RequireAuth])
def update_user(user_id: str, req: UserProfileUpdate):
    """更新用户画像（部分更新）"""
    profile = get_user_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在，请先运行 --setup")

    updates = req.model_dump(exclude_none=True)
    for key, value in updates.items():
        profile[key] = value

    save_user_profile(user_id, profile)
    return UserProfileResponse(user_id=user_id, profile=profile)


# ══════════════════════════════════════════════════════
# 自动规则
# ══════════════════════════════════════════════════════

@app.get("/api/v1/users/{user_id}/auto-rules", dependencies=[RequireAuth])
def get_rules(user_id: str):
    """查询用户的自动规则"""
    return get_auto_rules(user_id)


@app.post("/api/v1/users/{user_id}/auto-rules", response_model=AutoRuleResponse, dependencies=[RequireAuth])
def add_rule(user_id: str, req: AutoRuleRequest):
    """添加自动规则（block/accept/notify）"""
    try:
        add_auto_rule(user_id, req.rule_type, req.pattern, req.category)
        return AutoRuleResponse(ok=True, message=f"规则已添加: {req.rule_type} \"{req.pattern}\"")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ══════════════════════════════════════════════════════
# 知识库增量学习
# ══════════════════════════════════════════════════════

@app.post("/api/v1/knowledge/learn", response_model=LearnResponse, dependencies=[RequireAuth])
def trigger_learn(req: LearnRequest):
    """触发知识库增量学习（从 review.jsonl）"""
    from config import get_user_dir, KNOWLEDGE_FILE
    from knowledge_base import init_vectorstore

    set_user(req.user_id)
    review_path = get_user_dir(req.user_id) / "review.jsonl"

    if not review_path.exists():
        return LearnResponse(ok=True, learned_count=0, message="暂无质检结果")

    entries = []
    with open(review_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    wrong_entries = [e for e in entries if e.get("review") == "wrong"]
    if not wrong_entries:
        return LearnResponse(ok=True, learned_count=0, message="所有质检样本均正确，无需学习")

    # 计算起始编号
    max_id = 0
    if KNOWLEDGE_FILE.exists():
        with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("编号"):
                    continue
                parts = line.split(",", 1)
                try:
                    max_id = max(max_id, int(parts[0]))
                except ValueError:
                    pass

    learned = 0
    with open(KNOWLEDGE_FILE, "a", encoding="utf-8") as f:
        for e in wrong_entries:
            max_id += 1
            text = e.get("input", "").replace(",", "，")
            cat = e.get("correct_category", e.get("category", ""))
            rule = e.get("rule", "从API学习")
            f.write(f"{max_id},{text},{cat},{rule}\n")
            learned += 1

    # 重建向量库
    init_vectorstore(force_rebuild=True)
    return LearnResponse(ok=True, learned_count=learned,
                         message=f"已学习 {learned} 条修正样本，向量库已重建")


# ══════════════════════════════════════════════════════
# 系统状态
# ══════════════════════════════════════════════════════

@app.get("/api/v1/stats", response_model=StatsResponse, dependencies=[RequireAuth])
def get_stats():
    """系统运行状态"""
    pipeline = get_pipeline()
    return StatsResponse(**pipeline.stats())


# ══════════════════════════════════════════════════════
# 直接入口
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
