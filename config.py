"""
言犀-AI智能通话管家 — 全局配置
支持智谱GLM系列（生产）和本地Ollama（开发）双后端切换
"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
USERS_DIR = DATA_DIR / "users"
CHROMA_DIR = ROOT_DIR / "chroma_db_v3"
KNOWLEDGE_FILE = DATA_DIR / "200条来电记录.txt"

# ── 当前活跃用户 ────────────────────────────────
_current_user_id: str | None = None


def set_user(user_id: str):
    global _current_user_id
    _current_user_id = user_id
    # 确保用户目录存在
    user_dir = USERS_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "calls.jsonl").touch(exist_ok=True)
    (user_dir / "scams.jsonl").touch(exist_ok=True)
    if not (user_dir / "profile.json").exists():
        print(f"[WARN] 用户 {user_id} 的画像不存在，使用默认值")


def get_user() -> str:
    if _current_user_id is None:
        raise RuntimeError("未设置当前用户，请先调用 config.set_user(user_id)")
    return _current_user_id


def get_user_dir(user_id: str | None = None) -> Path:
    uid = user_id or _current_user_id
    if uid is None:
        raise RuntimeError("未指定 user_id")
    return USERS_DIR / uid


def get_user_profile_path(user_id: str | None = None) -> Path:
    return get_user_dir(user_id) / "profile.json"


def get_user_calls_path(user_id: str | None = None) -> Path:
    return get_user_dir(user_id) / "calls.jsonl"


def get_user_scams_path(user_id: str | None = None) -> Path:
    return get_user_dir(user_id) / "scams.jsonl"


def get_user_review_path(user_id: str | None = None) -> Path:
    return get_user_dir(user_id) / "review.jsonl"


USER_PROFILES_FILE = DATA_DIR / "user_profiles.json"  # v2 旧格式，保留兼容

env_path = ROOT_DIR / "key.env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

LLM_BACKEND = os.getenv("LLM_BACKEND", "zhipu")

ZHIPU_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")
ZHIPU_MODEL = os.getenv("ZHIPU_MODEL", "glm-4-flash")
ZHIPU_TEMPERATURE = float(os.getenv("ZHIPU_TEMPERATURE", "0.3"))

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
HF_ENDPOINT = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")

ASR_ENGINE = os.getenv("ASR_ENGINE", "vosk")
VOSK_MODEL_PATH = ROOT_DIR.parent / "vosk-model-cn-0.22"
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
TTS_OUTPUT = ROOT_DIR / "reply.mp3"

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))

# Chroma 使用 L2 距离：0=完全相同, 2=完全相反。设为 1.2 过滤掉低相似度结果
RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "1.2"))

SESSION_MAX_AGE_MINUTES = int(os.getenv("SESSION_MAX_AGE", "5"))

DEBUG = os.getenv("YANXI_DEBUG", "false").lower() in ("1", "true", "yes")

# ── API 服务配置 ────────────────────────────────
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")  # 空=不校验，生产环境应设置


def print_config():
    print(f"LLM Backend: {LLM_BACKEND}")
    if LLM_BACKEND == "zhipu":
        print(f"  Model: {ZHIPU_MODEL} | Temp: {ZHIPU_TEMPERATURE}")
    else:
        print(f"  Model: {OLLAMA_MODEL} | URL: {OLLAMA_BASE_URL}")
    print(f"ASR Engine: {ASR_ENGINE}")
    print(f"RAG threshold: {RAG_SCORE_THRESHOLD}")
