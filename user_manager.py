"""
用户画像管理 — 加载配置、课程时间判断、偏好决策、来电白名单
v3.0: per-user profile + known_callers
"""
import json
from datetime import datetime, time

from config import get_user_profile_path, DEBUG

_profiles_cache: dict[str, dict] = {}
_cache_mtime: dict[str, float] = {}


def load_profiles(force_reload: bool = False) -> dict:
    """v2 兼容：加载旧 user_profiles.json"""
    from config import USER_PROFILES_FILE
    path = USER_PROFILES_FILE
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_user_profile(user_id: str, force_reload: bool = False) -> dict:
    """加载单个用户的画像"""
    global _profiles_cache, _cache_mtime
    path = get_user_profile_path(user_id)
    if not path.exists():
        # 尝试从旧格式迁移
        old_profiles = load_profiles()
        if user_id in old_profiles:
            profile = old_profiles[user_id]
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
            print(f"[MIGRATE] 已将 {user_id} 的画像迁移到 {path}")
            _profiles_cache[user_id] = profile
            _cache_mtime[user_id] = path.stat().st_mtime
            return profile
        print(f"[WARN] 用户 {user_id} 画像不存在: {path}")
        return {}
    mtime = path.stat().st_mtime
    if user_id in _profiles_cache and not force_reload and mtime == _cache_mtime.get(user_id):
        return _profiles_cache[user_id]
    with open(path, "r", encoding="utf-8") as f:
        _profiles_cache[user_id] = json.load(f)
    _cache_mtime[user_id] = mtime
    return _profiles_cache[user_id]


def get_user_profile(user_id: str) -> dict:
    """获取指定用户的画像"""
    return _load_user_profile(user_id)


def match_known_caller(user_id: str, text: str) -> dict | None:
    """
    检测文本来电是否匹配用户的 known_callers 白名单。
    返回匹配到的条目 {name, category} 或 None。
    """
    profile = get_user_profile(user_id)
    known = profile.get("known_callers", {})
    if not known:
        return None
    for caller_key, caller_info in known.items():
        if caller_key in text:
            if DEBUG:
                print(f"[CALLER] 白名单命中: {caller_key} -> {caller_info['category']}")
            return caller_info
    return None


def is_class_time(profile: dict, check_time: datetime | None = None) -> bool:
    """判断当前是否在用户的课程时段内"""
    if not profile or "class_schedule" not in profile:
        return False
    if check_time is None:
        check_time = datetime.now()
    ct = check_time.time()
    wd = check_time.weekday()  # 0=周一（与 Python 标准库一致）
    for slot in profile["class_schedule"]:
        day_rule = slot.get("day", "weekday")
        if day_rule == "weekday" and wd >= 5:
            continue
        if day_rule == "weekend" and wd < 5:
            continue
        start = time.fromisoformat(slot["start"])
        end = time.fromisoformat(slot["end"])
        if start <= ct <= end:
            return True
    return False


def get_delivery_preference(profile: dict, check_time: datetime | None = None) -> dict:
    """
    返回外卖/快递处理偏好
    {
        "auto_accept": bool,
        "location": str,
        "extra_rule": str | None
    }
    """
    if not profile:
        return {"auto_accept": False, "location": "门口", "extra_rule": None}
    if check_time is None:
        check_time = datetime.now()

    auto_enabled = profile.get("auto_accept_enabled", False)
    in_class = is_class_time(profile, check_time)
    location = profile.get("default_location", "门口")
    extra = profile.get("extra_rules", {}).get("快递") if in_class else None

    # 周末规则：weekend_auto_accept=false 时不代接
    is_weekend = check_time.weekday() >= 5
    weekend_ok = profile.get("weekend_auto_accept", False)

    should_auto = auto_enabled and in_class
    if is_weekend and not weekend_ok:
        should_auto = False

    return {
        "auto_accept": should_auto,
        "location": location,
        "extra_rule": extra,
    }


def should_escalate_immediately(profile: dict, text: str) -> bool:
    """判断是否应立刻通知机主（医院/急诊等级别）"""
    if not profile:
        return False
    esc = profile.get("escalation", {})
    if not esc.get("notify_immediately", True):
        return False
    urgent = esc.get("urgent_keywords", [])
    return any(kw in text for kw in urgent)


def get_escalation_config(profile: dict) -> dict:
    """返回通知配置"""
    if not profile:
        return {"notify_immediately": True, "urgent_keywords": []}
    return profile.get("escalation", {"notify_immediately": True, "urgent_keywords": []})


# ── 自动规则（从通话中学习）──────────────────────────

def get_auto_rules(user_id: str) -> dict:
    """返回用户的自动规则，若不存在则返回空默认值"""
    profile = get_user_profile(user_id)
    if not profile:
        return {"block": [], "accept": [], "notify": []}
    return profile.get("auto_rules", {"block": [], "accept": [], "notify": []})


def add_auto_rule(user_id: str, rule_type: str, pattern: str,
                  category: str, note: str = "从通话学习") -> None:
    """添加一条自动规则到用户画像，自动去重"""
    if rule_type not in ("block", "accept", "notify"):
        raise ValueError(f"Invalid rule_type: {rule_type}")
    profile = get_user_profile(user_id)
    if not profile:
        print(f"[WARN] 用户 {user_id} 画像不存在，无法添加规则")
        return
    auto_rules = profile.setdefault("auto_rules", {"block": [], "accept": [], "notify": []})
    target = auto_rules.setdefault(rule_type, [])
    for existing in target:
        if existing.get("pattern") == pattern:
            if DEBUG:
                print(f"[INFO] 规则 \"{pattern}\" 已存在，跳过")
            return
    target.append({"pattern": pattern, "category": category, "note": note})
    save_user_profile(user_id, profile)
    if DEBUG:
        print(f"[AUTO-RULE] {rule_type}: \"{pattern}\" → {category}")


def _match_rule_list(rules: list[dict], text: str) -> dict | None:
    """在规则列表中做子串匹配，返回第一条匹配的规则"""
    for rule in rules:
        if rule["pattern"] in text:
            return rule
    return None


def match_auto_block_rule(user_id: str, text: str) -> dict | None:
    """检查文本是否匹配自动拦截规则"""
    return _match_rule_list(get_auto_rules(user_id).get("block", []), text)


def match_auto_accept_rule(user_id: str, text: str) -> dict | None:
    """检查文本是否匹配自动放行规则"""
    return _match_rule_list(get_auto_rules(user_id).get("accept", []), text)


def match_auto_notify_rule(user_id: str, text: str) -> dict | None:
    """检查文本是否匹配自动通知规则"""
    return _match_rule_list(get_auto_rules(user_id).get("notify", []), text)


def save_user_profile(user_id: str, profile: dict):
    """保存用户画像"""
    from config import get_user_profile_path
    path = get_user_profile_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    # 清除缓存
    global _profiles_cache, _cache_mtime
    _profiles_cache.pop(user_id, None)
    _cache_mtime.pop(user_id, None)
