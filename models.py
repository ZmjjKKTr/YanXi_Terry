"""
Pydantic 模型 — API 请求/响应结构定义
可被 api.py 和未来的 Web 界面直接 import
"""
from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════
# 通话相关
# ══════════════════════════════════════════════════════

class NewCallRequest(BaseModel):
    user_id: str = Field(default="zmjjkk", description="用户 ID")


class NewCallResponse(BaseModel):
    session_id: str
    message: str = "通话已创建"


class TurnRequest(BaseModel):
    text: str = Field(..., min_length=1, description="来电文本")


class TurnResponse(BaseModel):
    session_id: str
    reply: str
    category: str = ""
    rule: str = ""
    confidence: str = ""
    decision_needed: bool = False
    turn: int = 0
    session_ended: bool = False


class CallSummary(BaseModel):
    session_id: str
    category: str = ""
    rule: str = ""
    confidence: str = ""
    turns: int = 0
    correction: str = ""
    all_inputs: list[str] = []


# ══════════════════════════════════════════════════════
# 质检相关
# ══════════════════════════════════════════════════════

class ReviewRequest(BaseModel):
    review: str = Field(..., pattern="^(correct|wrong)$", description="correct 或 wrong")
    correct_category: str | None = Field(default=None, description="review=wrong 时必填，如 外卖/快递")


class ReviewResponse(BaseModel):
    ok: bool = True
    message: str = ""


# ══════════════════════════════════════════════════════
# 用户相关
# ══════════════════════════════════════════════════════

class UserProfileResponse(BaseModel):
    user_id: str
    profile: dict


class UserProfileUpdate(BaseModel):
    campus: str | None = None
    default_location: str | None = None
    auto_accept_enabled: bool | None = None
    weekend_auto_accept: bool | None = None
    response_style: str | None = None
    extra_rules: dict[str, str] | None = None
    known_callers: dict[str, dict] | None = None
    # auto_rules 通过专门接口管理
    # class_schedule / escalation 也支持直接覆盖
    class_schedule: list[dict] | None = None
    escalation: dict | None = None


# ══════════════════════════════════════════════════════
# 知识库增量学习
# ══════════════════════════════════════════════════════

class LearnRequest(BaseModel):
    user_id: str = Field(default="zmjjkk")


class LearnResponse(BaseModel):
    ok: bool = True
    learned_count: int = 0
    message: str = ""


# ══════════════════════════════════════════════════════
# 系统状态
# ══════════════════════════════════════════════════════

class StatsResponse(BaseModel):
    active_sessions: int = 0
    total_sessions: int = 0
    completed_calls: int = 0


# ══════════════════════════════════════════════════════
# 自动规则
# ══════════════════════════════════════════════════════

class AutoRuleRequest(BaseModel):
    rule_type: str = Field(..., pattern="^(block|accept|notify)$")
    pattern: str = Field(..., min_length=1)
    category: str = Field(default="")


class AutoRuleResponse(BaseModel):
    ok: bool = True
    message: str = ""
