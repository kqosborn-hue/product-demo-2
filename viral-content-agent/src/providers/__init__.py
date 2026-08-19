"""数据源注册表：按优先级排列，上层按 supports() + available() 依次尝试。"""

from .base import AccountRef, BaseProvider, ProviderUnavailable, parse_account
from .browser import JinaReaderProvider, PlaywrightProvider
from .community import RedditProvider, V2exProvider
from .hackernews import HackerNewsProvider
from .search_api import SearchApiProvider
from .snapshot import SnapshotProvider, slugify

# 顺序即优先级：官方公开 API > 真浏览器 > 搜索工具 > 网页读取兜底
LIVE_PROVIDERS = [
    HackerNewsProvider,
    RedditProvider,
    V2exProvider,
    PlaywrightProvider,
    SearchApiProvider,
    JinaReaderProvider,
]

__all__ = [
    "AccountRef", "BaseProvider", "ProviderUnavailable", "parse_account",
    "HackerNewsProvider", "RedditProvider", "V2exProvider",
    "PlaywrightProvider", "SearchApiProvider", "JinaReaderProvider",
    "SnapshotProvider", "slugify", "LIVE_PROVIDERS",
]
