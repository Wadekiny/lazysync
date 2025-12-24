"""
SSH客户端模块
负责SSH连接和交互式认证处理

本模块只包含纯逻辑和数据层，不依赖任何UI组件。
通过回调函数机制与UI层解耦。
"""

from typing import Callable, Awaitable, List, Tuple, Optional
import asyncssh


class PasswordCancelledError(Exception):
    """用户取消密码输入异常"""
    pass


class InteractiveSSHClient(asyncssh.SSHClient):
    """
    交互式SSH客户端
    
    自定义SSHClient，通过回调函数机制处理密码输入。
    客户端只负责SSH认证逻辑，不包含任何UI相关代码。
    """
    
    # 密码提示回调函数类型：async (prompt: str, mask_input: bool) -> str
    PasswordPromptCallback = Callable[[str, bool], Awaitable[str]]
    
    def __init__(self, password_prompt_callback: PasswordPromptCallback):
        """
        初始化交互式SSH客户端
        
        Args:
            password_prompt_callback: 异步回调函数，用于提示用户输入密码
                                    参数: (prompt: str, mask_input: bool) -> str
                                    prompt: 提示文本
                                    mask_input: 是否隐藏输入（True=密码，False=普通文本）
                                    返回: 用户输入的字符串
        """
        super().__init__()
        self._password_prompt = password_prompt_callback
    
    async def kbdint_challenge_received(
        self, 
        name: str, 
        instructions: str, 
        lang: str, 
        prompts: List[Tuple[str, bool]]
    ) -> List[str]:
        """
        处理键盘交互式认证挑战
        
        Args:
            name: 挑战名称
            instructions: 服务器说明
            lang: 语言代码
            prompts: 提示列表，每个元素是(prompt_text, echo)元组
                    echo=False表示需要隐藏输入（密码），echo=True表示显示输入
            
        Returns:
            响应列表，对应每个prompt的输入值
        """
        responses: List[str] = []
        for prompt_text, echo in prompts:
            # echo=False表示密码输入（需要隐藏），echo=True表示普通输入（显示）
            try:
                response = await self._password_prompt(
                    prompt=prompt_text, 
                    mask_input=not echo
                )
            except PasswordCancelledError:
                # 用户取消密码输入，抛出异常中断认证流程
                raise
            responses.append(response)
        return responses
    
    async def password_auth_requested(self) -> Optional[str]:
        super().password_auth_requested
        """
        处理密码认证请求
        
        Returns:
            用户输入的密码字符串，如果用户取消则返回None
        """
        try:
            password = await self._password_prompt(
                prompt="Enter password", 
                mask_input=True,

            )
            return password
        except PasswordCancelledError:
            # 用户取消密码输入，返回 None 表示跳过密码认证
            return None
