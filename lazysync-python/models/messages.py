"""
消息类型定义模块
定义应用程序中使用的各种消息类型，用于组件间通信
"""

from pathlib import Path
from typing import Union, Optional
from textual.message import Message


class ItemSelectRequest(Message):
    """
    请求选择项（文件或目录）时发送的消息
    
    当用户在文件浏览器中选择某个文件或目录时，
    浏览器组件会发送此消息来通知其他组件。
    """
    def __init__(self, target_path: Union[Path, str]) -> None:
        """
        初始化选择请求消息
        
        Args:
            target_path: 被选中的文件或目录路径
        """
        self.target_path = target_path
        super().__init__()


class PathSelected(Message):
    """
    路径选择确认消息
    
    当Browser组件确定选择了某个路径后发送此消息，
    用于通知主应用更新对应的输入框。
    """
    def __init__(self, path: Union[Path, str], browser_id: Optional[str]) -> None:
        """
        初始化路径选择消息
        
        Args:
            path: 被选中的路径
            browser_id: 发送消息的浏览器组件ID（用于区分源路径和目标路径）
        """
        self.path = path
        self.browser_id = browser_id
        super().__init__()





class OptionSelected(Message):
    """
    选项选中消息
    
    当OptionsPanel中的选项被选中或高亮时发送此消息，
    用于更新选项描述显示区域。
    """
    def __init__(self, description: str) -> None:
        """
        初始化选项选中消息
        
        Args:
            description: 被选中选项的描述文本
        """
        self.description = description
        super().__init__()


class CommandExecuteRequest(Message):
    """
    命令执行请求消息
    
    当用户请求执行预览中的rsync命令时发送此消息。
    """
    def __init__(self, command: str) -> None:
        """
        初始化命令执行请求消息
        
        Args:
            command: 要执行的完整命令字符串
        """
        self.command = command
        super().__init__()
