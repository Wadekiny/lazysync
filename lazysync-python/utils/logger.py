"""
日志工具模块
提供统一的日志记录功能
"""

from pathlib import Path
from config.constants import DEBUG_LOG_PATH


def log(message: str) -> None:
    """
    将消息写入调试日志文件
    
    Args:
        message: 要记录的消息字符串
    """
    with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"{message}\n")
