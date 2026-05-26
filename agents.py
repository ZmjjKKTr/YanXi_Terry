"""
LLM Agent 模块 — 支持智谱 GLM 和本地 Ollama 双后端
v2.3: 加入 few-shot 示例，回复更稳定自然
"""
from zhipuai import ZhipuAI

from config import (
    LLM_BACKEND, ZHIPU_API_KEY, ZHIPU_MODEL, ZHIPU_TEMPERATURE,
    OLLAMA_MODEL, OLLAMA_BASE_URL, DEBUG
)

_zhipu_client = None


def _get_zhipu_client() -> ZhipuAI:
    global _zhipu_client
    if _zhipu_client is None:
        if not ZHIPU_API_KEY:
            raise ValueError("未设置 ZHIPUAI_API_KEY，请检查 key.env")
        _zhipu_client = ZhipuAI(api_key=ZHIPU_API_KEY)
    return _zhipu_client


def _call_zhipu(messages: list[dict], temperature: float = ZHIPU_TEMPERATURE) -> str:
    client = _get_zhipu_client()
    try:
        resp = client.chat.completions.create(
            model=ZHIPU_MODEL,
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"[ERROR] 智谱 API 调用失败: {e}")
        return "抱歉，我暂时无法处理，请稍后再试。"


def _call_ollama(messages: list[dict]) -> str:
    import requests
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.3},
    }
    try:
        resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except Exception as e:
        print(f"[ERROR] Ollama 调用失败: {e}")
        return "抱歉，我暂时无法处理，请检查本地模型是否运行。"


def call_llm(messages: list[dict]) -> str:
    if DEBUG:
        print(f"[{LLM_BACKEND}] 调用 LLM...")
    if LLM_BACKEND == "ollama":
        return _call_ollama(messages)
    return _call_zhipu(messages)


SYSTEM_PROMPT = (
    "你是「言犀」AI通话助手，帮大学生接电话。"
    "说话自然得像真人，每句1-3句话。"
    "禁止说「我是AI」「语音助手」「智能助理」之类的话。"
    "像帮室友接电话一样。"
)


# ══════════════════════════════════════════════════════
# 外卖/快递 Agent
# ══════════════════════════════════════════════════════

DELIVERY_FEWSHOT = """以下是正确回复的示例：

来电: 喂你的外卖到了给你放哪
回复: 放门口鞋柜旁边就行，谢谢啊

来电: 你要的卤肉饭卖完了能换鸡腿饭吗
回复: 行，换鸡腿饭吧，谢谢

来电: 路上有点堵会晚十分钟到
回复: 没事，路上慢点，不急

来电: 我在这转了半天找不到你那个楼
回复: 三栋在食堂后面，靠操场那边

来电: 你的快递要本人签收你现在方便下来吗
回复: 现在不太方便，你放东门快递柜吧，取件码发我就行

来电: 你外卖里是不是不要香菜但是店家好像放了
回复: 算了没事，下次注意就行

来电: 喂我给你放门口地上了啊
回复: 好的谢谢，放门口就行

请模仿以上风格回复。每个来电只回一句。」"""


def agent_delivery(
    user_input: str,
    rule: str,
    auto_accept: bool,
    location: str,
    user_name: str,
    extra_rule: str | None = None,
) -> str:
    context = f"对方来电内容：{user_input}"

    if rule:
        context += f"\n参考规则：{rule}"
    if extra_rule:
        context += f"\n机主要求：{extra_rule}"

    if auto_accept:
        context += f"\n机主{user_name}在上课，快递默认放{location}。请直接告知放{location}并简短感谢。"
    else:
        context += f"\n机主可能不便接听。如需问放哪，建议{location}。"

    context += "\n先判断对方到底在说什么（问放哪？要换货？通知晚了？找不到路？），再按实际场景回复。"

    return call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": DELIVERY_FEWSHOT + "\n\n" + context},
    ])


def agent_delivery_confirm(location: str) -> str:
    context = f"对方说放{location}。请给一句简短确认加感谢。"
    return call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ])


# ══════════════════════════════════════════════════════
# 诈骗/推销 Agent
# ══════════════════════════════════════════════════════

def agent_block_scam() -> str:
    return "不需要，谢谢。"


# ══════════════════════════════════════════════════════
# 重要来电 Agent
# ══════════════════════════════════════════════════════

IMPORTANT_FEWSHOT = """以下是正确回复示例：

来电: 你好这边是校医院你体检报告出来了
回复: 好的谢谢，他现在不方便接电话，我让他稍后回给您

来电: 我是辅导员今天下午三点在学院会议室开会
回复: 收到，我会转告他，请问是哪位老师？

来电: 这边是人民医院你母亲急诊住院了请尽快过来
回复: 好的我马上想办法通知他，请问在哪个科室？

来电: 我是HR恭喜你通过了一面下周二上午十点二面
回复: 好的，我记下了，他现在不方便我让他稍后回您确认

请模仿以上风格，简洁得体。」"""


def agent_important(user_input: str, user_name: str) -> str:
    context = (
        f"来电：{user_input}\n"
        f"机主{user_name}暂时不能接听。请确认收到信息，问来电人姓名或单位，告知稍后回电。"
    )
    return call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": IMPORTANT_FEWSHOT + "\n\n" + context},
    ])


# ══════════════════════════════════════════════════════
# 重要来电多轮对话 Agent（阶段2）
# ══════════════════════════════════════════════════════

IMPORTANT_MULTITURN_PROMPT = """你是「言犀」AI通话助手，正在帮机主接一个重要来电。

核心原则：
- 始终用"您"敬称，态度礼貌自然，像帮室友接电话
- 第1轮确认身份时，要问到具体的姓名或科室，不要只确认机构名就满足
- 对方后面轮次说过的事，不要再重复问

事务转达流程（共4轮）：
第1轮 — 先亲切回应，然后确认身份/事由。对方说了多少就问缺的部分，别把人家已经说清楚的再问一遍
第2轮 — 继续收集剩余信息。如果身份事由都已清楚，过渡到补充确认
第3轮 — 信息够了，问"您还有什么要补充的吗？"
第4轮 — 复述确认："好的，我给您复述一下，您要我转达的是：xxxxxx。对吗？" 对方确认后说再见

注意：
- 如果对方说"不用回电话/微信就行"，就不要再要电话
- 每次1-3句话，自然得体"""


def agent_important_multiturn(
    user_input: str,
    collected: dict[str, str],
    user_name: str,
    turn: int,
    all_inputs: list[str] | None = None,
) -> str:
    caller = collected.get("caller", "")
    reason = collected.get("reason", "")
    contact = collected.get("contact", "")

    # 对话历史 — 防止 agent 遗忘已说过的信息
    history = ""
    if all_inputs and len(all_inputs) > 1:
        for i, inp in enumerate(all_inputs, 1):
            history += f"对方第{i}轮：{inp}\n"

    info_status = f"""当前进度：
- 来电人/单位：{caller if caller else '（待确认）'}
- 具体事由：{reason if reason else '（待确认）'}
- 联系方式：{contact if contact else '（待确认）'}
当前第{turn}轮（事务转达共4轮：收集→补充确认→复述→结束）"""

    if turn == 1:
        task = "第1轮。先亲切回应，然后确认身份——问清对方具体是谁（姓名/科室/部门），不要只确认机构名。如果事由也还没说清楚，一并问。不用急着要联系方式。"
    elif turn == 2:
        task = "第2轮。继续收集，缺什么问什么。如果身份和事由都有了，可以说'我记下了'然后过渡到补充确认。不要重复问对方已经说过的事。"
    elif turn == 3:
        task = '第3轮（补充确认）。信息够了，用自然的语气问："您还有什么要补充的吗？"'
    else:  # turn == 4
        task = '第4轮（复述确认）。把对方要转达的事完整复述一遍："好的，我给您复述一下，您要我转达的是：xxxxxx。对吗？" 对方确认后友好说再见。对方说不用回电话就不要问联系方式。'

    context = f"对方本轮说：{user_input}\n\n{info_status}\n\n{task}"
    if history:
        context = f"对话记录：\n{history}\n{context}"

    return call_llm([
        {"role": "system", "content": IMPORTANT_MULTITURN_PROMPT},
        {"role": "user", "content": context},
    ])


# ══════════════════════════════════════════════════════
# 转接通知 Agent（阶段2）
# ══════════════════════════════════════════════════════

def escalation_agent(collected: dict[str, str], user_name: str,
                     all_inputs: list[str] | None = None) -> str:
    caller = collected.get("caller", "未知")
    reason = collected.get("reason", "未知")
    contact = collected.get("contact", "未留")

    dialog = ""
    if all_inputs:
        dialog = "\n".join(f"  对方: {inp}" for inp in all_inputs)

    prompt = f"""根据以下通话信息，生成一条简洁的通知摘要给机主{user_name}。

来电人：{caller}
事由：{reason}
联系方式：{contact}
{"对话记录：" + dialog if dialog else ""}

请以如下格式输出（每行一条，不要有多余内容）：
━━━━━━ 重要来电通知 ━━━━━━
来电人：（从对话中提取的名称或单位）
事由：（一句话概括）
联系方式：（如有）
建议：（一句话建议，如"建议尽快回电""仅供参考"等）
━━━━━━━━━━━━━━━━━━━━━━"""

    return call_llm([
        {"role": "system", "content": "你是言犀通知系统。根据通话内容生成简洁的来电摘要，帮助机主快速了解情况。"},
        {"role": "user", "content": prompt},
    ])


# ══════════════════════════════════════════════════════
# 通用兜底 Agent
# ══════════════════════════════════════════════════════

GENERAL_FEWSHOT = """以下是正确回复示例：

来电: 喂今天中午有空没一起去食堂吃饭
回复: 他现在不在旁边，你是哪位？我让他等会回你

来电: 喂你上次借我的充电宝啥时候还
回复: 他现在不方便接，你留个名字我让他回你电话

来电: 你好请问是计算机学院的同学吗我想找人组队
回复: 是的，他现在不在，你留个联系方式我转告他

请模仿以上风格。」"""


def agent_general(user_input: str) -> str:
    context = f"来电：{user_input}\n对方来电意图不明确。请礼貌问对方是哪位或者留个信息。"
    return call_llm([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": GENERAL_FEWSHOT + "\n\n" + context},
    ])
