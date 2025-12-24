"""
命令预览组件模块
显示rsync命令预览，支持执行命令
"""

from textual.widgets import Static
from textual.binding import Binding
from textual.message import Message

from models.messages import CommandExecuteRequest


class CommandPreview(Static):
    """
    可聚焦的命令预览组件
    
    显示rsync命令预览，按Enter键可以执行命令。
    """
    
    BINDINGS = [
        Binding("enter", "execute_command", "Execute", show=True),
    ]
    
    def __init__(self, *args, **kwargs):
        """
        初始化命令预览组件
        
        Args:
            *args: 传递给父类的参数
            **kwargs: 传递给父类的关键字参数
        """
        super().__init__(*args, **kwargs)
        self.can_focus = True
        self._command_text = str(args[0]) if args else ""
    
    def update(self, text: str) -> None:
        """
        更新命令文本
        
        Args:
            text: 新的命令文本
        """
        self._command_text = str(text)
        super().update(text)
    
    def action_execute_command(self) -> None:
        """执行预览中的命令"""
        command = self._command_text.strip()
        if not command:
            return
        
        # 通知App执行命令
        self.post_message(CommandExecuteRequest(command=command))
