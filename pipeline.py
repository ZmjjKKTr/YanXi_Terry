"""
全链路编排器 — 串联 ASR → 敏感词拦截 → RAG分类(每轮) → Agent回复 → TTS
v3.0: known_callers 白名单 + per-user 日志
v3.1: API 支持 — 线程安全 + 结构化返回 + 会话持久化
"""
import json
import threading
from datetime import datetime, timedelta
from collections import OrderedDict
from pathlib import Path

from knowledge_base import search_knowledge, init_vectorstore
from user_manager import (
    get_user_profile, get_delivery_preference, match_known_caller,
    should_escalate_immediately,
)
from agents import (
    agent_delivery, agent_delivery_confirm,
    agent_block_scam, agent_important, agent_general,
    agent_important_multiturn, escalation_agent,
)
from config import (
    SESSION_MAX_AGE_MINUTES, RAG_SCORE_THRESHOLD, DEBUG,
    get_user_calls_path, get_user_scams_path, get_user,
)

# 强敏感词：命中任一直接拦截（在 RAG 之前）
SCAM_KEYWORDS = [
    "公安局", "检察院", "法院", "警察", "民警", "刑侦",
    "涉嫌", "洗钱", "通缉", "逮捕令", "传票",
    "中奖", "奖金", "领奖", "手续费", "保证金",
    "银行卡", "转账", "安全账户", "冻结", "密码",
    "免费保险", "优惠活动", "办理贷款", "无抵押",
    "房产中介", "装修公司", "链家", "贝壳找房",
]

# 外卖/快递特征词：RAG 误分类到"普通来电"时用于纠偏
DELIVERY_SIGNAL = [
    "外卖", "快递", "骑手", "跑腿", "送餐", "取餐", "取件",
    "配送", "送达", "放哪里", "给你放", "放门口", "放楼下",
    "放前台", "门禁", "取件码", "驿站", "快递柜", "外卖柜", "丰巢",
    "签收", "到付", "包裹", "送过来", "美团", "饿了么", "叮咚",
    "到了", "给你送",
]

# 重要来电特征词
IMPORTANT_SIGNAL = [
    "医院", "体检", "住院", "急诊", "手术",
    "辅导员", "导师", "教务处", "学院", "答辩", "复试",
    "面试", "录取", "奖学金", "助学贷款",
    "派出所", "认领", "物业通知", "停水", "停电",
]

# 需机主决策的信号词：AI 不应代决定换/退/改
DECISION_NEEDED_SIGNAL = [
    "换", "退", "卖完了", "没有了", "缺货", "缺材料",
    "做错了", "发错了", "搞错了", "颜色不对",
    "洒了", "破了", "坏了", "碎了",
    "取消了", "改一下", "能不能",
]

def notify_user(summary: str):
    """转接通知 — MVP 阶段终端打印，将来接推送/短信等"""
    print("\n" + "=" * 50)
    print(summary)
    print("=" * 50 + "\n")


class SessionState:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.profile: dict = get_user_profile(user_id)
        self.confirmed_location: str | None = None
        self.latest_category: str = ""
        self.latest_rule: str = ""
        self.last_active: datetime = datetime.now()
        self.turn: int = 0
        # 重要来电多轮对话
        self.important_stage: int = 0  # 0=非重要来电, 1-3=当前轮次
        self.important_info: dict[str, str] = {"caller": "", "reason": "", "contact": ""}
        self.important_inputs: list[str] = []
        # 分类元数据（供通话结束后质检分析）
        self.rag_results: list[dict] = []
        self.correction_applied: str = ""
        self.final_confidence: str = ""
        self.auto_rule_match: dict | None = None
        self.all_inputs: list[str] = []

    @property
    def is_expired(self) -> bool:
        return datetime.now() - self.last_active > timedelta(minutes=SESSION_MAX_AGE_MINUTES)

    def touch(self):
        self.last_active = datetime.now()


class Pipeline:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, SessionState] = OrderedDict()
        self._call_summaries: dict[str, dict] = {}  # session_id → 已完成通话摘要
        self._call_counter: int = 0
        print("[INIT] 初始化知识库...")
        init_vectorstore()
        self._load_state()
        print("[OK] 言犀全链路已就绪")

    def _get_session(self, session_id: str, user_id: str) -> SessionState:
        with self._lock:
            if session_id in self._sessions:
                state = self._sessions[session_id]
                if state.is_expired:
                    del self._sessions[session_id]
                else:
                    self._sessions.move_to_end(session_id)
                    return state
            state = SessionState(user_id)
            self._sessions[session_id] = state
            self._sessions.move_to_end(session_id)
            while len(self._sessions) > 50:
                self._sessions.popitem(last=False)
            return state

    def new_session(self, user_id: str) -> str:
        """生成新会话 ID 并初始化 SessionState（用于 API 预先创建通话）"""
        with self._lock:
            self._call_counter += 1
            sid = f"call_{self._call_counter:03d}"
            state = SessionState(user_id)
            self._sessions[sid] = state
            self._sessions.move_to_end(sid)
            while len(self._sessions) > 50:
                self._sessions.popitem(last=False)
            return sid

    # ── 关键词检测 ──────────────────────────────────

    @staticmethod
    def _has_scam_keywords(text: str) -> bool:
        return any(kw in text for kw in SCAM_KEYWORDS)

    @staticmethod
    def _check_delivery_signal(text: str) -> bool:
        return any(kw in text for kw in DELIVERY_SIGNAL)

    @staticmethod
    def _check_decision_needed(text: str) -> bool:
        """检测是否涉及换菜/退货/缺货/损坏等需机主决策的场景"""
        return any(kw in text for kw in DECISION_NEEDED_SIGNAL)

    @staticmethod
    def _check_important_signal(text: str) -> bool:
        return any(kw in text for kw in IMPORTANT_SIGNAL)

    @staticmethod
    def _check_auto_block(user_id: str, text: str) -> dict | None:
        from user_manager import match_auto_block_rule
        return match_auto_block_rule(user_id, text)

    @staticmethod
    def _check_auto_accept(user_id: str, text: str) -> dict | None:
        from user_manager import match_auto_accept_rule
        return match_auto_accept_rule(user_id, text)

    @staticmethod
    def _check_auto_notify(user_id: str, text: str) -> dict | None:
        from user_manager import match_auto_notify_rule
        return match_auto_notify_rule(user_id, text)

    @staticmethod
    def _extract_location(text: str) -> str | None:
        keywords = [
            "东门", "西门", "南门", "北门", "门口",
            "前台", "快递柜", "外卖柜", "驿站", "楼下", "丰巢",
            "保安亭", "大厅", "物业", "门卫", "收发室",
        ]
        for kw in keywords:
            if kw in text:
                return kw
        return None

    # ── 分类纠偏 ────────────────────────────────────

    def _correct_category(self, text: str, category: str, results: list[dict]) -> str:
        """
        当 RAG 分类不置信或明显不合理时，用关键词信号纠偏。
        返回修正后的 category。
        """
        # RAG 返回"普通来电"但文本有强外卖信号 → 纠偏
        if "普通" in category and self._check_delivery_signal(text):
            # 再确认 top-3 中有没有外卖/快递
            for r in results:
                if "外卖" in r["category"] or "快递" in r["category"]:
                    if DEBUG:
                        print(f"[FIX] 关键词纠偏: 普通来电 -> {r['category']}")
                    return r["category"]
            # top-3 全错也强制纠偏，不依赖 RAG 结果
            if DEBUG:
                print(f"[FIX] 强外卖信号，RAG全错，强制纠偏 -> 外卖/快递")
            return "外卖/快递"

        # RAG 返回"普通来电"但文本有重要来电信号 → 纠偏
        if "普通" in category and self._check_important_signal(text):
            for r in results:
                if "重要" in r["category"]:
                    if DEBUG:
                        print(f"[FIX] 关键词纠偏: 普通来电 -> {r['category']}")
                    return r["category"]
            if DEBUG:
                print(f"[FIX] 强重要信号，强制纠偏 -> 重要来电")
            return "重要来电"

        return category

    # ── 通话日志 ────────────────────────────────────

    def _log_call(self, session_id: str, text: str, category: str, rule: str, response: str):
        entry = {
            "time": datetime.now().isoformat(),
            "session": session_id,
            "input": text,
            "category": category,
            "rule": rule,
            "response": response,
        }
        try:
            log_path = get_user_calls_path()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 日志写入失败不影响主流程

    def _log_scam(self, text: str):
        """将拦截的诈骗文本写入用户诈骗黑名单"""
        try:
            scam_path = get_user_scams_path()
            entry = {"time": datetime.now().isoformat(), "text": text}
            with open(scam_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── 主处理流程 ──────────────────────────────────

    def process(self, session_id: str, text: str, user_id: str = "zmjjkk") -> str:
        """CLI 兼容：返回纯文本回复。API 请用 process_structured()"""
        result = self.process_structured(session_id, text, user_id)
        return result["reply"]

    def process_structured(self, session_id: str, text: str, user_id: str = "zmjjkk") -> dict:
        """处理一轮对话，返回结构化结果。线程安全。"""
        response: dict = {
            "session_id": session_id,
            "reply": "",
            "category": "",
            "rule": "",
            "confidence": "",
            "decision_needed": False,
            "turn": 0,
            "session_ended": False,
        }

        with self._lock:
            state = self._get_session(session_id, user_id)
        state.touch()
        state.turn += 1
        response["turn"] = state.turn

        # === 第 0 关前：重要来电多轮进行中，跳过分类直接继续 ===
        if state.important_stage > 0:
            reply = self._handle_important(session_id, state, text)
            response.update(reply=reply, category="重要来电(多轮)",
                          rule=f"stage={state.important_stage}",
                          confidence="high",
                          session_ended=state.important_stage > 4)
            self._log_call(session_id, text, response["category"], response["rule"], reply)
            if response["session_ended"]:
                self._save_state()
            return response

        # === 第 0 关-拦截：自动拦截规则 ===
        block_rule = self._check_auto_block(user_id, text)
        if block_rule:
            if DEBUG:
                print(f"[AUTO-BLOCK] 命中自动拦截: \"{block_rule['pattern']}\"")
            state.auto_rule_match = block_rule
            state.latest_category = f"自动拦截({block_rule.get('category','')})"
            state.final_confidence = "high"
            state.all_inputs.append(text)
            reply = agent_block_scam()
            response.update(reply=reply, category=state.latest_category,
                          confidence="high", session_ended=True)
            self._log_call(session_id, text, state.latest_category, "(自动拦截)", reply)
            self._end_session(session_id, state)
            self._save_state()
            return response

        # === 第 0 关：来电白名单（known_callers）直接放行 ===
        caller_match = match_known_caller(user_id, text)
        if caller_match:
            if DEBUG:
                print(f"[CALLER] 白名单直接路由 -> {caller_match['category']}")
            cat = caller_match["category"]
            if "外卖" in cat or "快递" in cat:
                reply = self._handle_delivery(session_id, state, text, cat, "")
                response.update(reply=reply, category=cat, rule="(白名单)")
            elif "重要" in cat:
                reply = self._handle_important(session_id, state, text)
                response.update(reply=reply, category=cat, rule="(白名单)",
                              session_ended=state.important_stage > 4)
            else:
                reply = agent_general(text)
                response.update(reply=reply, category=cat, rule="(白名单)",
                              session_ended=True)
            self._log_call(session_id, text, cat, "(白名单)", reply)
            if response["session_ended"]:
                self._save_state()
            return response

        # === 第 0 关-放行：自动放行规则 ===
        accept_rule = self._check_auto_accept(user_id, text)
        if accept_rule:
            if DEBUG:
                print(f"[AUTO-ACCEPT] 命中自动放行: \"{accept_rule['pattern']}\"")
            state.auto_rule_match = accept_rule
            state.final_confidence = "high"
            state.all_inputs.append(text)
            cat = accept_rule.get("category", "")
            state.latest_category = cat
            if "外卖" in cat or "快递" in cat:
                reply = self._handle_delivery(session_id, state, text, cat, "")
            elif "重要" in cat:
                reply = self._handle_important(session_id, state, text)
            else:
                reply = agent_general(text)
            response.update(reply=reply, category=cat, confidence="high")
            self._log_call(session_id, text, cat, "(自动放行)", reply)
            return response

        # === 第 0 关-通知：自动通知规则（被动，不改变路由） ===
        notify_rule = self._check_auto_notify(user_id, text)
        if notify_rule:
            if DEBUG:
                print(f"[AUTO-NOTIFY] 命中通知规则: \"{notify_rule['pattern']}\"")
            notify_user(
                f"[自动提醒] 匹配规则 \"{notify_rule['pattern']}\" — "
                f"来电内容: {text[:60]}..."
            )

        # === 第 1 关：敏感词兜底拦截 ===
        if self._has_scam_keywords(text):
            if DEBUG:
                hits = [kw for kw in SCAM_KEYWORDS if kw in text]
                print(f"[SCAM] 会话 {session_id} 敏感词命中: {hits}")
            reply = agent_block_scam()
            response.update(reply=reply, category="诈骗/推销(关键词)",
                          confidence="high", session_ended=True)
            self._log_call(session_id, text, "诈骗/推销(关键词)", "", reply)
            self._log_scam(text)
            self._end_session(session_id, state)
            self._save_state()
            return response

        # === 第 2 关：RAG 检索 + 阈值 ===
        results = search_knowledge(text, k=3)
        best = results[0] if results else None
        category = best["category"] if best else ""
        rule = best["rule"] if best else ""

        state.latest_category = category
        state.latest_rule = rule
        state.rag_results = results[:]
        state.all_inputs.append(text)

        # 置信度评估
        if not best or best["score"] > RAG_SCORE_THRESHOLD:
            state.final_confidence = "low"
        elif best["score"] <= 0.8:
            state.final_confidence = "high"
        else:
            state.final_confidence = "medium"

        if DEBUG:
            print(f"[RAG] 会话 {session_id}:")
            for r in results:
                flag = " OK" if r["score"] <= RAG_SCORE_THRESHOLD else " OVER"
                print(f"  score={r['score']:.4f} | {r['category']} | {r['rule']}{flag}")

        if not best or best["score"] > RAG_SCORE_THRESHOLD:
            if DEBUG:
                s = best["score"] if best else 'N/A'
                print(f"[WARN] score={s} > {RAG_SCORE_THRESHOLD}，兜底")
            if self._check_delivery_signal(text):
                if DEBUG:
                    print("[FIX] 超阈值但有外卖信号，按外卖处理")
                reply = self._handle_delivery(session_id, state, text, "外卖/快递", "")
                response.update(reply=reply, category="外卖/快递(纠偏)",
                              confidence="low")
                self._log_call(session_id, text, "外卖/快递(纠偏)", "", reply)
                return response
            reply = agent_general(text)
            response.update(reply=reply, category="未知(低置信)", confidence="low")
            self._log_call(session_id, text, "未知(低置信)", "", reply)
            return response

        # === 第 2.5 关：关键词纠偏 ===
        original_category = category
        category = self._correct_category(text, category, results)
        if category != original_category:
            state.correction_applied = f"关键词纠偏: {original_category} → {category}"

        # === 第 2.6 关：反向校验 ===
        if ("外卖" in category or "快递" in category) and best["score"] > 0.65:
            if not self._check_delivery_signal(text):
                if DEBUG:
                    print(f"[FIX] RAG返回{category}(score={best['score']:.2f})但缺少外卖/快递信号词，改走通用")
                state.correction_applied = f"反向校验: {category} → 普通来电"
                category = "普通来电"
                rule = ""

        if DEBUG:
            print(f"  最终分类: {category} | {rule}")

        # === 第 3 关：路由 ===
        if "诈骗" in category or "推销" in category:
            reply = agent_block_scam()
            response.update(reply=reply, category=category, rule=rule,
                          confidence=state.final_confidence, session_ended=True)
            self._log_call(session_id, text, category, rule, reply)
            self._log_scam(text)
            self._end_session(session_id, state)
            self._save_state()
            return response

        if "重要" in category or "紧急" in category:
            reply = self._handle_important(session_id, state, text)
            response.update(reply=reply, category=category, rule=rule,
                          confidence=state.final_confidence,
                          session_ended=state.important_stage > 4)
            self._log_call(session_id, text, category, rule, reply)
            return response

        if "外卖" in category or "快递" in category:
            decision = self._check_decision_needed(text)
            reply = self._handle_delivery(session_id, state, text, category, rule)
            response.update(reply=reply, category=category, rule=rule,
                          confidence=state.final_confidence,
                          decision_needed=decision)
            self._log_call(session_id, text, category, rule, reply)
            return response

        # 普通来电 / 兜底
        reply = agent_general(text)
        response.update(reply=reply, category=category, rule=rule,
                      confidence=state.final_confidence)
        self._log_call(session_id, text, category, rule, reply)
        return response

    def _handle_delivery(self, session_id: str, state: SessionState, text: str, category: str, rule: str) -> str:
        from datetime import datetime
        pref = get_delivery_preference(state.profile)
        location = self._extract_location(text)

        # 换菜/退货/缺货/损坏等需机主决策 → 转接，不代决定
        if self._check_decision_needed(text):
            notify_user(
                f"[需决策] {state.user_id}，外卖/快递来电需你决定\n"
                f"内容: {text[:80]}\n"
                f"（涉及换/退/改，AI 不代决定）"
            )
            reply = agent_delivery(
                text, rule, auto_accept=False,
                location=pref["location"],
                user_name=state.user_id,
                extra_rule="涉及换货/退货/改单需要机主决定，你不能替他做任何决定。告诉对方：'机主现在不方便，麻烦您直接在APP里给他发个消息说明情况，他会回复您。'",
            )
            return reply

        if pref["auto_accept"]:
            reply = agent_delivery(
                text, rule, auto_accept=True,
                location=pref["location"],
                user_name=state.user_id,
                extra_rule=pref["extra_rule"],
            )
            self._end_session(session_id, state)
            return reply

        # 周末 → 根据用户画像决定是否转接
        if datetime.now().weekday() >= 5:
            weekend_auto = state.profile.get("weekend_auto_accept", False)
            if not weekend_auto:
                notify_user(
                    f"[周末转接] {state.user_id}，有外卖/快递来电\n"
                    f"内容: {text[:80]}\n"
                    f"（如需周末代接，请用 --setup 开启）"
                )
                reply = agent_delivery(
                    text, rule, auto_accept=False,
                    location=pref["location"],
                    user_name=state.user_id,
                    extra_rule="机主周末不方便代接，请让对方稍后发短信或APP内留言，不要替机主做决定。",
                )
                return reply
            # weekend_auto_accept=true → 按正常逻辑继续（允许周末代接）

        if location:
            state.confirmed_location = location
            reply = agent_delivery_confirm(location)
            self._end_session(session_id, state)
            return reply

        return agent_delivery(
            text, rule, auto_accept=False,
            location=pref["location"],
            user_name=state.user_id,
        )

    def _handle_important(self, session_id: str, state: SessionState, text: str) -> str:
        from datetime import datetime
        stage = state.important_stage
        is_urgent = should_escalate_immediately(state.profile, text)
        is_weekend = datetime.now().weekday() >= 5

        # 周末重要来电 — 机主更可能空闲，强制紧急通知
        if is_weekend and not is_urgent:
            is_urgent = True

        # 累积所有用户输入，供 agent/escalation 做完整对话理解
        state.important_inputs.append(text)

        # 医疗紧急关键词 → 预填事由，帮助通知系统快速判断
        if any(kw in text for kw in ["住院", "急诊", "手术", "重伤", "抢救"]):
            state.important_info["reason"] = text

        if stage == 0:
            state.important_stage = 1

            # 紧急来电：首轮即通知机主，但不挂断，继续收集信息
            if is_urgent:
                partial = escalation_agent(
                    state.important_info, state.user_id,
                    all_inputs=state.important_inputs,
                )
                tag = "[周末·紧急]" if is_weekend else "[紧急]"
                notify_user(
                    f"{tag} 正在通话中，持续获取详情...\n{partial}"
                )

            response = agent_important_multiturn(
                text, state.important_info, state.user_id, turn=1,
                all_inputs=state.important_inputs,
            )
            return response

        state.important_stage = stage + 1

        # 事务转达 4 阶段：收集(1-2) → 补充确认(3) → 复述(4) → 结束
        if state.important_stage > 4:
            # 最终汇总通知
            summary = escalation_agent(
                state.important_info, state.user_id,
                all_inputs=state.important_inputs,
            )
            if is_urgent and is_weekend:
                prefix = "[周末·更新] 通话结束，完整信息:"
            elif is_urgent:
                prefix = "[更新] 通话结束，完整信息:"
            else:
                prefix = ""
            notify_user(prefix + summary)
            self._end_session(session_id, state)
            return f"好的，我会尽快转告{state.user_id}。再见！"

        # 紧急来电中途也更新通知
        if is_urgent and state.important_stage >= 2:
            partial = escalation_agent(
                state.important_info, state.user_id,
                all_inputs=state.important_inputs,
            )
            tag = "[周末·更新]" if is_weekend else "[更新]"
            notify_user(f"{tag} 获取到更多信息...\n{partial}")

        response = agent_important_multiturn(
            text, state.important_info, state.user_id,
            turn=state.important_stage,
            all_inputs=state.important_inputs,
        )
        return response

    def _build_summary_from_state(self, session_id: str, state: SessionState) -> dict:
        return {
            "session_id": session_id,
            "category": state.latest_category,
            "rule": state.latest_rule,
            "confidence": state.final_confidence,
            "correction": state.correction_applied,
            "rag_scores": state.rag_results,
            "turns": state.turn,
            "auto_rule_match": state.auto_rule_match,
            "all_inputs": state.all_inputs,
        }

    def _store_call_summary(self, session_id: str, state: SessionState):
        with self._lock:
            self._call_summaries[session_id] = self._build_summary_from_state(session_id, state)
            while len(self._call_summaries) > 50:
                self._call_summaries.pop(next(iter(self._call_summaries)))

    def _end_session(self, session_id: str, state: SessionState):
        self._store_call_summary(session_id, state)
        with self._lock:
            self._sessions.pop(session_id, None)

    def get_call_summary(self, session_id: str) -> dict | None:
        with self._lock:
            if session_id in self._call_summaries:
                return self._call_summaries.pop(session_id)
            if session_id in self._sessions:
                return self._build_summary_from_state(session_id, self._sessions[session_id])
        return None

    def reset_session(self, session_id: str):
        with self._lock:
            if session_id in self._sessions:
                self._store_call_summary(session_id, self._sessions[session_id])
            self._sessions.pop(session_id, None)
            self._save_state()

    def stats(self) -> dict:
        now = datetime.now()
        with self._lock:
            active = sum(1 for s in self._sessions.values() if not s.is_expired)
            total = len(self._sessions)
        return {"active_sessions": active, "total_sessions": total, "completed_calls": len(self._call_summaries)}

    # ── 会话持久化 ──────────────────────────────────

    def _save_state(self):
        """将会话状态持久化到磁盘（服务重启恢复）"""
        from config import DATA_DIR
        state_path = DATA_DIR / "sessions.json"
        try:
            data = {
                "call_counter": self._call_counter,
                "sessions": {},
                "summaries": self._call_summaries,
            }
            for sid, state in self._sessions.items():
                data["sessions"][sid] = {
                    "user_id": state.user_id,
                    "profile": {},  # profile 从文件重新加载，不持久化
                    "confirmed_location": state.confirmed_location,
                    "latest_category": state.latest_category,
                    "latest_rule": state.latest_rule,
                    "last_active": state.last_active.isoformat(),
                    "turn": state.turn,
                    "important_stage": state.important_stage,
                    "important_info": state.important_info,
                    "important_inputs": state.important_inputs,
                    "rag_results": state.rag_results,
                    "correction_applied": state.correction_applied,
                    "final_confidence": state.final_confidence,
                    "auto_rule_match": state.auto_rule_match,
                    "all_inputs": state.all_inputs,
                }
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass  # 持久化失败不影响主流程

    def _load_state(self):
        """从磁盘恢复会话状态"""
        from config import DATA_DIR
        state_path = DATA_DIR / "sessions.json"
        if not state_path.exists():
            return
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._call_counter = data.get("call_counter", 0)
            self._call_summaries = data.get("summaries", {})
            for sid, sd in data.get("sessions", {}).items():
                state = SessionState(sd["user_id"])
                state.confirmed_location = sd.get("confirmed_location")
                state.latest_category = sd.get("latest_category", "")
                state.latest_rule = sd.get("latest_rule", "")
                state.last_active = datetime.fromisoformat(sd["last_active"]) if sd.get("last_active") else datetime.now()
                state.turn = sd.get("turn", 0)
                state.important_stage = sd.get("important_stage", 0)
                state.important_info = sd.get("important_info", {"caller": "", "reason": "", "contact": ""})
                state.important_inputs = sd.get("important_inputs", [])
                state.rag_results = sd.get("rag_results", [])
                state.correction_applied = sd.get("correction_applied", "")
                state.final_confidence = sd.get("final_confidence", "")
                state.auto_rule_match = sd.get("auto_rule_match")
                state.all_inputs = sd.get("all_inputs", [])
                if not state.is_expired:
                    self._sessions[sid] = state
            if self._sessions:
                print(f"[LOAD] 恢复了 {len(self._sessions)} 个活跃会话")
        except Exception:
            pass  # 恢复失败不影响启动


_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline


def process_message(text: str, session_id: str = "call_001", user_id: str = "zmjjkk") -> str:
    return get_pipeline().process(session_id, text, user_id)
