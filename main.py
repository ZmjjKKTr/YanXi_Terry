"""
言犀-AI智能通话管家 — 主入口
模式：
  python main.py                    文本模拟测试（默认用户 zmjjkk）
  python main.py --user zmjjkk      指定用户
  python main.py --voice            真实语音模式（麦克风 + TTS 回复）
  python main.py --rebuild          重建向量库后进入测试
  python main.py --review           通话质检模式
  python main.py --learn            知识库增量学习（从质检修正样本入库）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import DEBUG, print_config, set_user, get_user, get_user_review_path
from pipeline import Pipeline
from knowledge_base import init_vectorstore
from user_manager import add_auto_rule


# ── 实时通话后质检 + 自动规则 ──────────────────────

def _suggest_pattern(text: str, category: str) -> str:
    """从已知关键词库匹配最长关键词作为自动规则建议"""
    from pipeline import SCAM_KEYWORDS, DELIVERY_SIGNAL, IMPORTANT_SIGNAL
    if "诈骗" in category or "推销" in category:
        candidates = SCAM_KEYWORDS
    elif "外卖" in category or "快递" in category:
        candidates = DELIVERY_SIGNAL
    elif "重要" in category:
        candidates = IMPORTANT_SIGNAL
    else:
        candidates = SCAM_KEYWORDS + DELIVERY_SIGNAL + IMPORTANT_SIGNAL
    best = ""
    for kw in candidates:
        if kw in text and len(kw) > len(best):
            best = kw
    return best if best else text[:8]


def _save_single_review(input_text: str, summary: dict, response: str,
                        review_result: str) -> None:
    """实时写入单条质检结果到 review.jsonl，格式兼容批量 --review"""
    import json
    from datetime import datetime
    entry = {
        "time": datetime.now().isoformat(),
        "session": summary.get("session_id", ""),
        "input": input_text,
        "category": summary.get("category", ""),
        "rule": summary.get("rule", ""),
        "response": response,
        "review_time": datetime.now().isoformat(),
    }
    if review_result == "correct":
        entry["review"] = "correct"
    elif review_result.startswith("wrong|"):
        entry["review"] = "wrong"
        entry["correct_category"] = review_result.split("|", 1)[1]
    review_path = get_user_review_path()
    with open(review_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def post_call_interactive(pipeline: Pipeline, session_id: str,
                          last_input: str, last_response: str) -> None:
    """通话结束后的三步交互：自动分析 → 质检 → 自动规则"""
    summary = pipeline.get_call_summary(session_id)
    if not summary:
        return

    # ── Step A: 自动分析 ──
    print("\n" + "=" * 55)
    print(f"  通话结束 [{session_id}] — 自动分析")
    print("=" * 55)
    print(f"  最终分类 : {summary['category']}")
    print(f"  规则标签 : {summary['rule']}")
    print(f"  置信度   : {summary['confidence']}")
    if summary.get("correction"):
        print(f"  已纠偏   : {summary['correction']}")
    if summary.get("auto_rule_match"):
        ar = summary["auto_rule_match"]
        print(f"  自动规则 : {ar['pattern']} → {ar.get('note', '')}")
    rag = summary.get("rag_scores", [])
    if rag:
        print(f"  RAG top-3:")
        for i, r in enumerate(rag[:3], 1):
            print(f"    {i}. [{r['category']}] score={r['score']:.4f} | {r['rule']}")

    print(f"\n  来电原文 : {last_input}")
    print(f"  系统回复 : {last_response}")

    # ── Step B: 质检 ──
    while True:
        choice = input("\n  是否需要质检这条通话? (y/n): ").strip().lower()
        if choice in ("y", "n"):
            break

    if choice == "y":
        while True:
            judge = input("  分类正确? (y=正确 / n=错误): ").strip().lower()
            if judge in ("y", "n"):
                break

        if judge == "y":
            _save_single_review(last_input, summary, last_response, "correct")
            print("  [OK] 已标记为正确")
        else:
            CAT_MAP = {"1": "外卖/快递", "2": "诈骗/推销", "3": "重要来电", "4": "普通来电"}
            print("  1=外卖/快递  2=诈骗/推销  3=重要来电  4=普通来电")
            while True:
                corr = input("  正确分类 (1-4 或自定义): ").strip()
                if corr in CAT_MAP:
                    corr = CAT_MAP[corr]
                if corr:
                    break
            _save_single_review(last_input, summary, last_response, f"wrong|{corr}")
            print(f"  [OK] 已标记为: {corr}")

    # ── Step C: 自动规则 ──
    print(f"\n  设置自动规则（从这通电话学习）:")
    print(f"    1 = 此类来电一律放行")
    print(f"    2 = 此类来电一律拦截")
    print(f"    3 = 此类来电短信通知机主")
    print(f"    4 = 跳过")

    while True:
        rc = input("  选择 (1-4): ").strip()
        if rc in ("1", "2", "3", "4"):
            break

    if rc != "4":
        suggested = _suggest_pattern(last_input, summary.get("category", ""))
        print(f"  建议匹配词: \"{suggested}\"")
        pattern = input(f"  确认或修改 (回车确认): ").strip()
        if not pattern:
            pattern = suggested
        if not pattern:
            print("  匹配词不能为空，已跳过。")
            return
        type_map = {"1": "accept", "2": "block", "3": "notify"}
        name_map = {"accept": "一律放行", "block": "一律拦截", "notify": "短信通知"}
        add_auto_rule(get_user(), type_map[rc], pattern, summary.get("category", ""))
        print(f"  [OK] 已添加规则: \"{pattern}\" → {name_map[type_map[rc]]}")


def run_text_mode(pipeline: Pipeline):
    print("=" * 55)
    print(f"  言犀 AI 智能通话管家 — 文本模拟模式")
    print(f"  当前用户: {get_user()}")
    print("  输入来电内容，AI 自动分类并生成回复")
    print("  输入 'quit' 退出 | 输入 'new' 开始新通话")
    print("=" * 55)

    session_id = "call_001"
    call_counter = 1

    while True:
        try:
            user_input = input(f"\n[{session_id}] 来电内容: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n测试结束。")
            break

        if user_input.lower() in ('quit', 'q', 'exit'):
            break
        if user_input.lower() == 'new':
            call_counter += 1
            session_id = f"call_{call_counter:03d}"
            print(f"[NEW] 新会话: {session_id}")
            continue
        if not user_input:
            continue

        response = pipeline.process(session_id, user_input, get_user())
        print(f">> 言犀回复: {response}")

        end_keywords = ["不需要", "已确认", "稍后回电", "再见", "会尽快转告"]
        if any(kw in response for kw in end_keywords):
            post_call_interactive(pipeline, session_id, user_input, response)
            call_counter += 1
            session_id = f"call_{call_counter:03d}"
            print("[END] 通话结束，准备接听下一通...")


def run_voice_mode(pipeline: Pipeline):
    from speech.asr import recognize_from_mic
    from speech.tts import synthesize
    import time

    print("=" * 55)
    print(f"  言犀 AI 智能通话管家 — 语音模式")
    print(f"  当前用户: {get_user()}")
    print("  Ctrl+C 退出")
    print("=" * 55)

    session_id = "call_001"
    call_counter = 1

    try:
        while True:
            text = recognize_from_mic(duration=8)
            if not text:
                continue

            print(f"[ASR] 识别文本: {text}")

            response = pipeline.process(session_id, text, get_user())
            print(f">> 言犀回复: {response}")

            synthesize(response, play=True)

            end_keywords = ["不需要", "已确认", "稍后回电", "再见", "会尽快转告"]
            if any(kw in response for kw in end_keywords):
                post_call_interactive(pipeline, session_id, text, response)
                call_counter += 1
                session_id = f"call_{call_counter:03d}"
                print("[END] 通话结束")
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n语音模式结束。")


def run_setup_wizard():
    """交互式设置向导 — 帮用户配置个人习惯"""
    import json
    from user_manager import save_user_profile

    print("=" * 55)
    print("  言犀 个人习惯设置向导")
    print("  回答几个问题，帮你配置代接偏好")
    print("=" * 55)

    uid = input("\n你的用户名 (默认 zmjjkk): ").strip() or "zmjjkk"
    set_user(uid)
    campus = input("学校名称 (默认 暨南大学): ").strip() or "暨南大学"
    location = input("快递/外卖默认放哪里 (默认 东门快递柜): ").strip() or "东门快递柜"

    print("\n--- 课表设置 ---")
    print("周一到周五上课时段，用空格分隔（如 8:30-12:10 14:00-18:00）")
    schedule_input = input("上课时段 (回车用默认): ").strip()
    if schedule_input:
        slots = []
        parts = schedule_input.split()
        for p in parts:
            if "-" in p:
                start, end = p.split("-")
                slots.append({"day": "weekday", "start": start.strip(), "end": end.strip()})
    else:
        slots = [
            {"day": "weekday", "start": "08:30", "end": "12:10"},
            {"day": "weekday", "start": "14:00", "end": "18:00"},
        ]

    auto = input("上课时段自动代接外卖/快递？(y/n, 默认 y): ").strip().lower() != "n"
    weekend = input("周末也自动代接吗？(y/n, 默认 n): ").strip().lower() == "y"

    print("\n--- 通知优先级 ---")
    print("哪些情况应该立刻通知你？（已预设医院/急诊/派出所等）")
    custom_urgent = input("添加自定义紧急关键词 (逗号分隔, 回车跳过): ").strip()
    urgent_kw = ["医院", "急诊", "手术", "派出所", "住院", "重伤", "抢救"]
    if custom_urgent:
        urgent_kw.extend(k.strip() for k in custom_urgent.split(",") if k.strip())

    print("\n--- 常见联系人 ---")
    print("添加几个常用联系人，格式: 名称=分类（外卖/快递 或 重要来电）")
    print("例如: 顺丰快递员=外卖/快递, 妈妈=重要来电")
    contacts_input = input("联系人 (逗号分隔, 回车用默认): ").strip()
    if contacts_input:
        callers = {}
        for item in contacts_input.split(","):
            if "=" in item:
                name, cat = item.split("=", 1)
                callers[name.strip()] = {"name": name.strip(), "category": cat.strip()}
    else:
        callers = {
            "顺丰快递员": {"name": "顺丰", "category": "外卖/快递"},
            "美团骑手": {"name": "美团", "category": "外卖/快递"},
            "妈妈": {"name": "妈妈", "category": "重要来电"},
            "爸爸": {"name": "爸爸", "category": "重要来电"},
        }

    profile = {
        "name": uid,
        "campus": campus,
        "default_location": location,
        "class_schedule": slots,
        "auto_accept_enabled": auto,
        "weekend_auto_accept": weekend,
        "escalation": {
            "urgent_keywords": urgent_kw,
            "notify_immediately": True,
        },
        "response_style": "简洁礼貌",
        "extra_rules": {
            "快递": f"贵重物品请放丰巢柜",
            "外卖": "放门口鞋柜旁即可",
        },
        "known_callers": callers,
        "auto_rules": {
            "block": [],
            "accept": [],
            "notify": [],
        },
    }

    save_user_profile(uid, profile)
    print(f"\n[OK] 用户 {uid} 的配置已保存！")
    print(f"  自动代接: {'上课时段' if auto else '关闭'}")
    print(f"  周末代接: {'开启' if weekend else '关闭'}")
    print(f"  紧急通知: {', '.join(urgent_kw[:5])}...")
    print(f"  联系人: {len(callers)} 人")


def run_review_mode():
    """通话质检模式 — 交互式逐条质检 + 统计面板"""
    import json
    from datetime import datetime
    from config import get_user_calls_path, get_user_dir, get_user

    log_path = get_user_calls_path()
    if not log_path.exists():
        print("暂无通话记录。")
        return

    entries = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    if not entries:
        print("暂无通话记录。")
        return

    # 过滤低置信度通话（系统"犹豫过"的）
    reviewable = []
    for e in entries:
        cat = e.get("category", "")
        rule = e.get("rule", "")
        if any(tag in cat for tag in ["纠偏", "低置信"]) or "反向" in rule:
            reviewable.append(e)

    if not reviewable:
        print(f"共 {len(entries)} 条通话，无需质检（均为高置信度）。")
        return

    print(f"\n===== 通话质检（{len(reviewable)}/{len(entries)} 条待检）=====")
    print("系统对以下通话分类不置信，请逐条判断。")
    print("  y = 分类正确   n = 分类错误    s = 跳过")
    print("  错误时请选正确分类: 1外卖/快递 2诈骗/推销 3重要来电 4普通来电")
    print("=" * 55)

    CATEGORY_MAP = {"1": "外卖/快递", "2": "诈骗/推销", "3": "重要来电", "4": "普通来电"}

    results = []
    for i, e in enumerate(reviewable, 1):
        print(f"\n--- [{i}/{len(reviewable)}] ---")
        print(f"原文: {e.get('input', '?')}")
        print(f"系统分类: {e.get('category', '?')}")
        print(f"系统回复: {e.get('response', '?')}")

        while True:
            choice = input("判断 (y/n/s): ").strip().lower()
            if choice in ('y', 'n', 's'):
                break
            print("  请输入 y / n / s")

        if choice == 's':
            results.append({**e, "review": "skipped"})
            continue

        if choice == 'y':
            results.append({**e, "review": "correct"})
            continue

        # choice == 'n': 分类错误，让用户选正确分类
        while True:
            correct = input("正确分类 (1-4 或自定义): ").strip()
            if correct in CATEGORY_MAP:
                correct = CATEGORY_MAP[correct]
            if correct:
                break
            print("  请输入有效分类")

        results.append({**e, "review": "wrong", "correct_category": correct})
        print(f"  -> 已标记为: {correct}")

    # 统计面板
    total = len(results)
    correct = sum(1 for r in results if r.get("review") == "correct")
    wrong = sum(1 for r in results if r.get("review") == "wrong")
    skipped = sum(1 for r in results if r.get("review") == "skipped")
    reviewed = correct + wrong

    print("\n" + "=" * 50)
    print("  质检统计")
    print("=" * 50)
    print(f"  待检总数: {total}")
    print(f"  已检: {reviewed}  |  正确: {correct}  |  错误: {wrong}  |  跳过: {skipped}")
    if reviewed > 0:
        print(f"  准确率: {correct / reviewed * 100:.1f}%")

    # 类型分布
    print(f"\n  系统分类分布:")
    from collections import Counter
    sys_dist = Counter(r.get("category", "?") for r in results)
    for cat, cnt in sys_dist.most_common():
        print(f"    {cat}: {cnt}")

    if wrong > 0:
        print(f"\n  误匹配详情:")
        for r in results:
            if r.get("review") == "wrong":
                print(f"    系统判「{r.get('category','?')}」→ 人工标「{r.get('correct_category','?')}」")
                print(f"      原文: {r.get('input','?')}")

    # 保存质检结果
    try:
        review_path = get_user_dir() / "review.jsonl"
        for r in results:
            r["review_time"] = datetime.now().isoformat()
        with open(review_path, "a", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n  [OK] 质检结果已保存至 {review_path}")
    except Exception:
        pass

    learnable = sum(1 for r in results if r.get("review") == "wrong")
    if learnable > 0:
        print(f"  [TIP] {learnable} 条修正样本可加入知识库，运行 python main.py --learn")


def run_learn_mode():
    """知识库增量学习 — 从 review.jsonl 提取修正样本，确认后入库"""
    import json
    from config import get_user_dir, get_user, KNOWLEDGE_FILE, CHROMA_DIR

    review_path = get_user_dir() / "review.jsonl"
    if not review_path.exists():
        print("暂无质检结果。请先运行 python main.py --review 进行通话质检。")
        return

    entries = []
    with open(review_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    wrong_entries = [e for e in entries if e.get("review") == "wrong"]
    if not wrong_entries:
        print("所有质检样本均正确，无需增量学习。")
        return

    print(f"\n===== 知识库增量学习（{len(wrong_entries)} 条修正样本）=====")
    print("将逐条展示修正样本，确认后加入知识库。")
    print("  y = 确认入库   n = 跳过   e = 编辑规则标签后入库")
    print("=" * 55)

    # 读取当前知识库最大编号
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

    # 规则标签自动建议
    RULE_SUGGEST = {
        "门禁": "门禁问题", "定位": "定位问题", "快递柜": "快递柜通知",
        "驿站": "驿站提醒", "联系": "联系失败", "放门口": "无接触配送",
        "配送": "配送进度", "签收": "签收确认", "取件码": "验证码签收",
        "前台": "代收通知", "延迟": "延迟通知", "破损": "异常处理",
        "冒充": "冒充身份", "积分": "积分诈骗", "征信": "征信诈骗",
        "贷款": "贷款诈骗", "中奖": "中奖诈骗", "转账": "转账诈骗",
        "保证金": "保证金诈骗", "医院": "医疗通知", "辅导员": "学校通知",
        "面试": "求职相关", "答辩": "学校通知",
    }

    def suggest_rule(text: str, category: str) -> str:
        for kw, rule in RULE_SUGGEST.items():
            if kw in text:
                return rule
        if "外卖" in category or "快递" in category:
            return "通用配送"
        elif "诈骗" in category or "推销" in category:
            return "疑似诈骗"
        elif "重要" in category:
            return "重要通知"
        return "通用"

    confirmed = []
    for i, e in enumerate(wrong_entries, 1):
        text = e.get("input", "")
        sys_cat = e.get("category", "")
        correct_cat = e.get("correct_category", "")
        suggested_rule = suggest_rule(text, correct_cat)

        print(f"\n--- [{i}/{len(wrong_entries)}] ---")
        print(f"原文: {text}")
        print(f"系统误判: {sys_cat}")
        print(f"人工标注: {correct_cat}")
        print(f"建议规则: {suggested_rule}")

        while True:
            choice = input("操作 (y=确认入库 / n=跳过 / e=编辑规则): ").strip().lower()
            if choice in ("y", "n", "e"):
                break
            print("  请输入 y / n / e")

        if choice == "n":
            continue

        rule = suggested_rule
        if choice == "e":
            rule = input(f"请输入规则标签 (回车保留'{suggested_rule}'): ").strip() or suggested_rule

        max_id += 1
        confirmed.append((max_id, text, correct_cat, rule))
        print(f"  -> 已确认 #{max_id}: [{correct_cat}] {rule}")

    if not confirmed:
        print("\n未选择任何样本，知识库未变更。")
        return

    print(f"\n===== 确认入库 {len(confirmed)} 条 =====")
    final = input("确认写入知识库并重建向量库? (y/n): ").strip().lower()
    if final != "y":
        print("已取消。")
        return

    # 写入知识库
    with open(KNOWLEDGE_FILE, "a", encoding="utf-8") as f:
        for cid, ctext, ccat, crule in confirmed:
            f.write(f"{cid},{ctext},{ccat},{crule}\n")
    print(f"[OK] 已追加 {len(confirmed)} 条至 {KNOWLEDGE_FILE.name}（当前共 {max_id} 条）")

    # 重建向量库
    print("重建向量库...")
    init_vectorstore(force_rebuild=True)
    print(f"[OK] 向量库重建完成，知识库增量学习结束。")


def main():
    parser = argparse.ArgumentParser(description="言犀-AI智能通话管家")
    parser.add_argument("--user", type=str, default="zmjjkk", help="指定用户（默认 zmjjkk）")
    parser.add_argument("--voice", action="store_true", help="语音模式（麦克风 + TTS）")
    parser.add_argument("--rebuild", action="store_true", help="重建向量库")
    parser.add_argument("--review", action="store_true", help="通话质检模式")
    parser.add_argument("--learn", action="store_true", help="知识库增量学习（从 review.jsonl 提取修正样本入库）")
    parser.add_argument("--setup", action="store_true", help="个人习惯设置向导")
    parser.add_argument("--debug", action="store_true", help="开启调试输出")
    args = parser.parse_args()

    if args.debug:
        import config
        config.DEBUG = True
        print_config()

    # 设置当前用户
    set_user(args.user)

    if args.setup:
        run_setup_wizard()
        return

    if args.review:
        run_review_mode()
        return

    if args.learn:
        run_learn_mode()
        return

    if args.rebuild:
        print("重建向量库...")
        init_vectorstore(force_rebuild=True)
        print("[OK] 向量库重建完成")

    pipeline = Pipeline()

    if args.voice:
        run_voice_mode(pipeline)
    else:
        run_text_mode(pipeline)


if __name__ == "__main__":
    main()
