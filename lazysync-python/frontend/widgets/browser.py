"""
文件浏览器组件模块
包含本地和远程文件系统的浏览UI组件
"""

import os
from functools import wraps
from textual.message import Message
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Union
from textual.containers import Vertical
from textual.widgets import Input, ListView, ListItem, Label, Static
from textual.binding import Binding
from textual.reactive import reactive

from backend.file_manager import LocalFileManager, SSHFileManager
from utils.logger import log
from backend.ssh_client import InteractiveSSHClient, PasswordCancelledError
from frontend.widgets.base.list_view_ui import ListViewUI




class EntryMenuUI(ListViewUI):
    """
    入口菜单UI组件
    
    用于显示文件系统选择菜单（本地/远程）。
    """
    
    BINDINGS = ListViewUI.BINDINGS.copy()
    BINDINGS += [
        Binding("l,enter", "comfirm_selected", "Confirm", show=True),
    ]

    def action_comfirm_selected(self):
        """l, enter: 进入选中的项"""
        if self.index is not None and self.index < len(self.children):
            item = self.children[self.index]
            label = item.query_one(Label)
            content = str(label.content)
            self.post_message(EntryConfirmRequested(content))

class PasswordEnterRequested(Message):
    """密码输入完成消息"""
    def __init__(self, password: str):
        self.password = password
        super().__init__()

class EntryConfirmRequested(Message):
    def __init__(self, content:str) -> None:
        self.content = content
        super().__init__()

class BorderTitleUpdateRequested(Message):
    def __init__(self, title:str, subtitle:str) -> None:
        self.title = title
        self.subtitle = subtitle
        super().__init__()

class GoBackRequested(Message):
    def __init__(self) -> None:
        super().__init__()

class SelectPathRequested(Message):
    def __init__(self, path, browser_id=None) -> None:
        self.path = path
        self.browser_id = browser_id
        super().__init__()

class RemoteConfigSubmit(Message):
    """
    远程SSH配置提交消息

    当用户完成远程SSH连接配置输入后发送此消息。
    """
    def __init__(self, host: str, username: str, port: int):
        """
        初始化远程配置消息
        
        Args:
            host: SSH服务器主机地址（IP或域名）
            username: SSH用户名
            port: SSH端口号
        """
        self.host = host
        self.username = username
        self.port = port
        super().__init__()


class LocalFileManagerUI(ListViewUI):
    """
    本地文件管理器UI组件
    
    用于显示本地目录内容的列表UI控件。
    """
    
    BINDINGS = ListViewUI.BINDINGS.copy()
    BINDINGS += [
        Binding("enter", "select_path", "Select", show=True),
        Binding("h", "go_parent_dir", "Parent", show=True),
        Binding("l", "enter_dir", "Enter", show=True),
        Binding("escape", "go_back", "Back", show=True),
        Binding(".", "toggle_hidden", "Toggle Hidden", show=True),
    ]
    dir_contents = reactive(list)
    
    #===watch===
    def watch_dir_contents(self, new_dir_contents):
        self.clear()
        for file_name, file_path  in self.dir_contents:
            self.append(ListItem(Label(file_name, markup=False)))
        self.reset_index()

    def watch_index(self, old_index: int | None, new_index: int | None) -> None:
        super().watch_index(old_index, new_index) # update highlighting
        self.reload_border_title()
        # update border title and subtitle, post message

    def __init__(self, initial_path: Optional[Union[Path, str]] = None, **kwargs):
        """
        初始化本地文件管理器UI
        
        Args:
            initial_path: 初始路径
            **kwargs: 传递给父类的其他参数
        """
        super().__init__(**kwargs)
        self.fm = LocalFileManager(initial_path or Path.home())
        self.show_hidden = False  # 默认不显示隐藏文件
    
    #===reload=== 
    @staticmethod
    def auto_reload_content_dir(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            self.reload_content_dir()
            return result
        return wrapper

    def reload_content_dir(self):
        """从FileManager重新加载目录内容"""
        self.dir_contents = self.fm.get_contents(show_hidden=self.show_hidden)

    def reload_border_title(self):
        title = str(self.fm.current_path)
        # 处理index为None的情况
        current_index = self.index if self.index is not None else 0
        index = current_index + 1
        total = len(self.dir_contents)
        subtitle = f"{index}/{total}"
        log(f'title:{title}, subtitle:{subtitle}')
        self.post_message(BorderTitleUpdateRequested(title,subtitle))

    #===on===
    @auto_reload_content_dir
    def on_mount(self):
        super().on_mount()

    #===action===
    @auto_reload_content_dir
    def action_go_parent_dir(self):
        """h: 返回父目录"""
        self.fm.change_parent()
    
    @auto_reload_content_dir
    def action_enter_dir(self):
        """l: 进入选中的目录"""
        if self.index != None:
            target_name, target_path = self.dir_contents[self.index]
            self.fm.change_dir(target_path)
    
    @auto_reload_content_dir
    def action_toggle_hidden(self):
        """.: 切换显示/隐藏隐藏文件和目录"""
        self.show_hidden = not self.show_hidden
    
    def action_go_back(self):
        """esc: 返回到入口菜单"""
        self.post_message(GoBackRequested())

    def action_select_path(self):
        """Enter：只负责"选中路径"，不负责导航"""
        if self.index != None:
            target_name, target_path = self.dir_contents[self.index]
            self.post_message(SelectPathRequested(path=target_path))


class SSHFileManagerUI(ListViewUI):
    """
    SSH远程文件管理器UI组件
    
    用于显示远程SSH目录内容的列表UI控件。
    """
    
    BINDINGS = ListViewUI.BINDINGS.copy()
    BINDINGS += [
        Binding("enter", "select_path", "Select", show=True),
        Binding("h", "go_parent_dir", "Parent", show=True),
        Binding("l", "enter_dir", "Enter", show=True),
        Binding("escape", "go_back", "Back", show=True),
        Binding(".", "toggle_hidden", "Toggle Hidden", show=True),
    ]
    dir_contents=reactive(list)    

    #===watch===
    def watch_dir_contents(self):
        self.clear()
        for file_name, file_path  in self.dir_contents:
            self.append(ListItem(Label(file_name, markup=False)))
        self.reset_index()

    def watch_index(self, old_index: int | None, new_index: int | None) -> None:
        super().watch_index(old_index, new_index) # update highlighting
        self.reload_border_title()

    def __init__(self, connect_kwargs: Dict[str, Any]):
        """
        初始化SSH文件管理器UI
        
        Args:
            browser: Browser组件实例
            connect_kwargs: SSH连接参数
        """
        super().__init__()
        self.fm = SSHFileManager()
        self.show_hidden = False  # 默认不显示隐藏文件
        self.connect_kwargs = connect_kwargs


    async def reload_content_dir(self):
        """从FileManager重新加载目录内容"""
        self.dir_contents = await self.fm.get_contents(show_hidden=self.show_hidden)

    def reload_border_title(self):
        username = self.connect_kwargs.get("username", "user")
        host = self.connect_kwargs.get("host", "host")
        current_path = self.fm.current_path
        title = f"{username}@{host}:{current_path}"

        current_index = self.index if self.index is not None else 0
        index = current_index + 1
        total = len(self.dir_contents)
        subtitle = f"{index}/{total}"
        self.post_message(BorderTitleUpdateRequested(title,subtitle))

    async def init_ssh(self):
        """初始化SSH连接"""
        connect_kwargs = self.connect_kwargs
        try:
            await self.fm.connect(**connect_kwargs)
            await self.reload_content_dir()
        except Exception as e:
            log(f"init_ssh error :{e}")
    
    def on_mount(self):
        """组件挂载时初始化SSH连接"""
        super().on_mount()
        # 注意：不要在这里调用 reload_content_dir()
        # 因为 init_ssh() 已经在 enter_remote() 中被调用，它会完成连接并调用 reload_content_dir()
    
    
    def action_enter_dir(self):
        """l: 进入选中的目录"""
        if self.index != None:
            target_name, target_path = self.dir_contents[self.index]
            async def _():
                await self.fm.change_dir(target_path)
                await self.reload_content_dir()
            self.run_worker(_())
    
    
    def action_go_parent_dir(self):
        """h: 返回父目录"""
        async def _():
            await self.fm.change_parent()
            await self.reload_content_dir()
        self.run_worker(_())
    
    def action_select_path(self):
        """Enter: 选中当前项"""
        if self.index is not None:
            target_name, target_path = self.dir_contents[self.index]
            target_path = f"{self.connect_kwargs['username']}@{self.connect_kwargs['host']}:{target_path}"
            self.post_message(SelectPathRequested(path=target_path))
    
    def action_toggle_hidden(self):
        self.show_hidden = not self.show_hidden
        self.run_worker(self.reload_content_dir())
    
    def action_go_back(self):
        self.post_message(GoBackRequested())


class RemoteConfigUI(Vertical):
    """
    SSH远程配置输入UI组件
    
    用于输入SSH连接信息（主机、用户名、端口）。
    """
    
    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
    ]
    
    def compose(self):
        """组合UI组件"""
        self.remote_host_input = Input(
            placeholder="Host (IP or domain)",
            id="remote_host",
            value="116.172.93.164",
        )
        self.remote_username_input = Input(
            placeholder="Username",
            id="remote_user",
            value="ubuntu"

        )
        self.remote_port_input = Input(
            placeholder="Port (default 22)",
            id="remote_port",
            value="29293",
        )
        
        yield self.remote_host_input
        yield self.remote_username_input
        yield self.remote_port_input
    
    def on_mount(self):
        """组件挂载时设置标题并聚焦第一个输入框"""
        self.remote_host_input.focus()
    
    def on_input_submitted(self, event: Input.Submitted):
        """处理输入提交事件"""
        self.submit()
    
    def submit(self):
        """提交配置信息"""
        host = self.remote_host_input.value.strip()
        user = self.remote_username_input.value.strip()
        port = int(self.remote_port_input.value or 22)
        
        self.post_message(RemoteConfigSubmit(host=host,username=user,port=port,))
    
    def action_go_back(self):
        """esc: 返回到入口菜单"""
        self.post_message(GoBackRequested())


class PasswordUI(Vertical):
    """
    密码输入模态框组件
    """
    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
    ]

    def __init__(
        self,
        prompt: str,
        future: asyncio.Future[str],
        mask_input: bool = True,
    ):
        super().__init__()
        self._future = future
        self.input_widget = Input(
            password=mask_input,
            placeholder=prompt,
        )
        self.input_widget.border_title = "SSH Interactive"

    def compose(self):
        yield self.input_widget

    def on_mount(self):
        self.input_widget.focus()

    def on_input_submitted(self, event: Input.Submitted):
        """用户提交密码"""
        if not self._future.done():
            self._future.set_result(event.value)
        self.remove()

    def on_unmount(self):
        """窗口被关闭但未输入"""
        if not self._future.done():
            self._future.cancel()

    def action_go_back(self):
        """esc: 取消密码输入并返回"""
        # 取消 future（如果还没完成）
        if not self._future.done():
            self._future.cancel()
        # 发送 goback 消息，让 Browser 切换回入口菜单
        self.post_message(GoBackRequested())


class Browser(Static):
    """
    文件浏览器主组件
    
    管理本地和远程文件系统的浏览，支持在两种模式间切换。
    """
    
    state = reactive("entry")
    """当前状态：entry（入口菜单）、local（本地）、remote_config（远程配置）、remote（远程）"""
    
    def on_mount(self):
        """组件挂载时初始化入口菜单"""
        self.enter_entry()

    @staticmethod
    def switch_mount(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            self.can_focus=True
            self.focus()
            result = func(self, *args, **kwargs)
            self.can_focus=False
            return result
        return wrapper


    @switch_mount
    def enter_entry(self, is_focus=False):
        """进入入口菜单状态"""
        # self.app.screen.focused = None
        self.remove_children()
        entry_ui = EntryMenuUI(
            ListItem(Label("Local filesystem")),
            ListItem(Label("Remote filesystem")),
            id="entry_menu",
        )
        self.mount(entry_ui)
        self.state = "entry"
        self.update_border_title()
        if is_focus:
            entry_ui.focus()

    
    def update_border_title(self, path_info: Optional[str] = None, subtitle=None):
        """
        更新 border title 根据当前状态和路径信息
        
        Args:
            path_info: 路径信息（本地路径或远程路径格式）
        """
        base_title = self.id
        
        if self.state == "entry":
            self.border_title = base_title
        elif self.state == "remote_config":
            self.border_title = f"{base_title} - SSHConfig"
        elif self.state == "local" and path_info:
            self.border_title = f"{base_title} - {path_info}"
        elif self.state == "remote" and path_info:
            self.border_title = f"{base_title} - {path_info}"
        else:
            self.border_title = base_title

        self.border_subtitle = subtitle
    
    @switch_mount
    def enter_local(self, initial_path: Optional[Path] = None):
        self.remove_children()
        list_ui = LocalFileManagerUI(
            initial_path=initial_path,
            id="local_fm",
        )
        self.mount(list_ui)
        self.state = "local"
        list_ui.focus()
    
    @switch_mount
    def enter_remote_config(self):
        """进入远程SSH配置输入模式"""
        self.remove_children()
        remote_config_ui = RemoteConfigUI(
            id="remote_config"
        )
        self.mount(remote_config_ui)
        self.state = "remote_config"
        self.update_border_title()
        remote_config_ui.focus()

    @switch_mount
    def enter_remote(self, connect_kwargs: Dict[str, Any]):
        self.remove_children()
        ssh_ui = SSHFileManagerUI(connect_kwargs=connect_kwargs)
        self.run_worker(ssh_ui.init_ssh())
        self.mount(ssh_ui)
        self.state = "remote"
        ssh_ui.focus()
    
    #===message===
    # goback
    def on_go_back_requested(self, message: GoBackRequested):
        """处理返回入口菜单请求"""
        if self.state != "entry":
            self.enter_entry(is_focus=True)



    # update border_title
    def on_border_title_update_requested(self, message:BorderTitleUpdateRequested):
        self.update_border_title(message.title, message.subtitle)
    
    def on_entry_confirm_requested(self, message: EntryConfirmRequested):
        """处理列表选择事件"""
        label = message.content
        if label == "Local filesystem":
            self.enter_local()
        elif label == "Remote filesystem":
            self.enter_remote_config()
    
    def on_select_path_requested(self, message: SelectPathRequested):
        """
        处理项选择请求消息
        
        Args:
            message: 项选择请求消息
        """
        message.browser_id = self.id




    
    def on_remote_config_submit(self, message: RemoteConfigSubmit):
        """
        处理远程配置提交消息
        
        Args:
            message: 远程配置提交消息
        """
        async def password_prompt_callback(prompt: str, mask_input: bool) -> str:
            """
            密码提示回调函数适配器, 用于提供给ssh client, 需要密码输入时调用这个函数，并等待其返回密码
            被cancel，则raise passwordcancelledError
            """
            loop = asyncio.get_running_loop()
            future: asyncio.Future[str] = loop.create_future()

            modal = PasswordUI(
                prompt=prompt,
                mask_input=mask_input,
                future=future,
            )
            self.state = "SSH Interactive"
            self.mount(modal)


            try:
                return await future
            except asyncio.CancelledError:
                # 用户取消密码输入，抛出 PasswordCancelledError 异常
                raise PasswordCancelledError("Password input was cancelled by user")
        
        connect_kwargs = {
            "host": message.host,
            "port": message.port,
            "username": message.username,
            "client_factory": lambda: InteractiveSSHClient(
                password_prompt_callback=password_prompt_callback
            ),
            "known_hosts": None,
        }
        self.enter_remote(connect_kwargs)
    


