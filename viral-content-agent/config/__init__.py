"""配置层：settings（环境变量/路径） + prompts（角色设定与各阶段 Prompt）。"""

from .settings import (ASSET_DIR, BASE_DIR, DATA_DIR, SESSION_DIR, SNAPSHOT_DIR,
                       Settings, get_settings, load_dotenv)

__all__ = ["BASE_DIR", "DATA_DIR", "SNAPSHOT_DIR", "ASSET_DIR", "SESSION_DIR",
           "Settings", "get_settings", "load_dotenv"]
