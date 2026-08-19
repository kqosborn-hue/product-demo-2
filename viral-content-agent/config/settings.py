"""全局配置：所有敏感信息只从环境变量 / .env 读取，禁止硬编码。

设计原则
--------
1. 零硬依赖：内置极简 .env 解析器，未安装 python-dotenv 也能运行。
2. 敏感信息隔离：API Key、账号、库表 ID 全部走 .env（模板见 .env.example）。
3. 人工确认不可关闭：HITL 闸门是流程完整性的一部分，不提供 env 开关。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------- 路径
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
ASSET_DIR = DATA_DIR / "assets"
SESSION_DIR = DATA_DIR / "sessions"

for _d in (SNAPSHOT_DIR, ASSET_DIR, SESSION_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- .env
def load_dotenv(path: Optional[Path] = None, override: bool = False) -> dict:
    """极简 .env 解析器（支持 # 注释、KEY=VALUE、引号包裹、export 前缀）。"""
    path = Path(path) if path else BASE_DIR / ".env"
    loaded: dict = {}
    if not path.exists():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(_env(key, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------- Settings
@dataclass
class Settings:
    # ---- LLM（OpenAI 兼容协议；缺省时自动降级为规则引擎） ----
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.7
    llm_timeout: int = 60

    # ---- 数据获取 ----
    data_source: str = "auto"          # auto | live | snapshot
    default_account: str = "hn:topic:AI agent"
    lookback_days: int = 30
    fetch_limit: int = 60
    top_high_performers: int = 3       # 高表现内容 1-3 条
    control_group_size: int = 3        # 普通内容对照组 2-3 条
    random_seed: int = 42              # 对照组随机抽样种子（保证可复现）

    # ---- 搜索 / 抓取通道 ----
    search_provider: str = "serper"    # serper | tavily | bocha
    serper_api_key: str = ""
    tavily_api_key: str = ""
    bocha_api_key: str = ""
    jina_reader_base: str = "https://r.jina.ai/"
    http_timeout: int = 25
    user_agent: str = "viral-content-agent/1.0 (+https://github.com/)"

    # ---- 资产库 ----
    asset_backend: str = "json"        # json | notion | feishu
    asset_file: Path = field(default_factory=lambda: ASSET_DIR / "content_assets.json")
    notion_token: str = ""
    notion_database_id: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_bitable_app_token: str = ""
    feishu_bitable_table_id: str = ""

    # ---- 运行时 ----
    color: bool = True
    max_revision_rounds: int = 3

    # 人工确认闸门：常量，不可通过配置关闭
    require_human_approval: bool = field(default=True, init=False)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key and self.llm_base_url)


_cached: Optional[Settings] = None


def get_settings(reload: bool = False) -> Settings:
    global _cached
    if _cached is not None and not reload:
        return _cached
    load_dotenv()
    s = Settings(
        llm_base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_api_key=_env("LLM_API_KEY"),
        llm_model=_env("LLM_MODEL", "gpt-4o-mini"),
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.7),
        llm_timeout=_env_int("LLM_TIMEOUT", 60),
        data_source=_env("DATA_SOURCE", "auto").lower(),
        default_account=_env("TARGET_ACCOUNT", "hn:topic:AI agent"),
        lookback_days=_env_int("LOOKBACK_DAYS", 30),
        fetch_limit=_env_int("FETCH_LIMIT", 60),
        top_high_performers=max(1, min(3, _env_int("TOP_HIGH_PERFORMERS", 3))),
        control_group_size=max(2, min(3, _env_int("CONTROL_GROUP_SIZE", 3))),
        random_seed=_env_int("RANDOM_SEED", 42),
        search_provider=_env("SEARCH_PROVIDER", "serper").lower(),
        serper_api_key=_env("SERPER_API_KEY"),
        tavily_api_key=_env("TAVILY_API_KEY"),
        bocha_api_key=_env("BOCHA_API_KEY"),
        jina_reader_base=_env("JINA_READER_BASE", "https://r.jina.ai/"),
        http_timeout=_env_int("HTTP_TIMEOUT", 25),
        asset_backend=_env("ASSET_BACKEND", "json").lower(),
        notion_token=_env("NOTION_TOKEN"),
        notion_database_id=_env("NOTION_DATABASE_ID"),
        feishu_app_id=_env("FEISHU_APP_ID"),
        feishu_app_secret=_env("FEISHU_APP_SECRET"),
        feishu_bitable_app_token=_env("FEISHU_BITABLE_APP_TOKEN"),
        feishu_bitable_table_id=_env("FEISHU_BITABLE_TABLE_ID"),
        color=_env("NO_COLOR", "") == "",
        max_revision_rounds=_env_int("MAX_REVISION_ROUNDS", 3),
    )
    custom_asset = _env("ASSET_FILE")
    if custom_asset:
        s.asset_file = Path(custom_asset)
    _cached = s
    return s
