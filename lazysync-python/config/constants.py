"""
应用程序常量定义
"""

import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 配置文件路径
OPTIONS_JSON_PATH = PROJECT_ROOT / "options.json"
STYLE_CSS_PATH = PROJECT_ROOT / "style.css"
DEBUG_LOG_PATH = PROJECT_ROOT / "debug.log"

# 默认SSH端口
DEFAULT_SSH_PORT = 22

# UI相关常量
APP_TITLE = "LazySync"
