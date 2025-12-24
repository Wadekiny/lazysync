"""
主应用模块
LazySync TUI应用程序的主入口
"""

import asyncio
from textual.app import App, ComposeResult
from textual.widgets import Footer, Label, Markdown, TabbedContent, TabPane
from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import (
    Header,
    Footer,
    Input,
    Static,
    RichLog,
    Checkbox,
)
from textual.binding import Binding

from config.constants import STYLE_CSS_PATH, APP_TITLE
from models.messages import (
    PathSelected,
    OptionSelected,
    CommandExecuteRequest,
)
from frontend.widgets.browser import Browser, SelectPathRequested
from frontend.widgets.options_panel import OptionsPanel, ValueOptionsPanel
from frontend.widgets.command_preview import CommandPreview
from backend.rsync_command_builder import RsyncCommandBuilder
from backend.command_executor import CommandExecutor


class LazySyncUI(App):
    """
    LazySync主应用类
    
    负责整合所有UI组件，处理用户交互，构建和执行rsync命令。
    """
    
    CSS_PATH = str(STYLE_CSS_PATH)
    TITLE = APP_TITLE
    
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("tab", "focus_next", "Focus Next", show=True),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "edit", "Edit", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]
    
    def action_cancel(self) -> None:
        """处理esc键取消操作"""
        # 检查是否有value_options的输入框正在编辑
        try:
            value_opts = self.query_one("#value_options", ValueOptionsPanel)
            if value_opts.editing_input is not None:
                value_opts.action_cancel_edit()
                return
        except:
            pass
    
    def compose(self) -> ComposeResult:
        """
        组合UI组件
        
        创建应用程序的布局结构：
        - 顶部：Header
        - 主区域：Grid布局，包含路径输入、文件浏览器、选项面板、描述、预览、日志
        - 底部：Footer
        """
        yield Header(id="header", show_clock=True)
        
        with Grid():
            # Row 1: 路径输入框
            inp_src = Input(placeholder="Enter source path...", id="source", classes="span_path")
            inp_src.border_title = "Source Path"
            yield inp_src
            
            inp_tgt = Input(placeholder="Enter target path...", id="target", classes="span_path")
            inp_tgt.border_title = "Target Path"
            yield inp_tgt
            
            # Row 2: 文件浏览器
            br_src = Browser(id="source_browser", classes="span_browser")
            yield br_src
            
            br_tgt = Browser(id="target_browser", classes="span_browser")
            yield br_tgt
            
            # Row 3: 选项面板（短选项、长选项、值选项）
            short_opts = OptionsPanel(show_short=True, classes="span_option")
            short_opts.border_title = "Short Options"
            yield short_opts
            
            long_opts = OptionsPanel(show_short=False, classes="span_option")
            long_opts.border_title = "Long Options"
            yield long_opts
            
            value_opts = ValueOptionsPanel(classes="span_option")
            value_opts.border_title = "Value Options"
            yield value_opts
            
            # Row 4: 选项描述（跨所有列）
            desc = Static("Select an option to see its description", id="desc", classes="span_desc")
            desc.border_title = "Option Description"
            yield desc
            
            # Row 5: 命令预览
            preview = CommandPreview("rsync", id="preview", classes="span_cmd")
            preview.border_title = "Command Preview"
            yield preview
            
            # Row 6: 执行日志
            logs = RichLog(id="logs", classes="span_log", markup=True)
            logs.border_title = "Execution Log"
            yield logs
            
            # Row 7: 命令输入框（用于向运行的进程发送输入）
            cmd_input = Input(placeholder="Enter input for running process (press Enter to send)...", id="cmd_input", classes="span_cmd")
            cmd_input.border_title = "Process Input"
            cmd_input.disabled = True  # 默认禁用，只有在进程运行时才启用
            yield cmd_input
            with TabbedContent(initial="jessica"):
                with TabPane("Leto", id="leto"):
                    yield Markdown("hello")
                with TabPane("Jessica", id="jessica"):
                    yield Markdown("jess")
                with TabPane("Paul", id="paul"):
                    yield Markdown("scp")
        
        # Footer with key bindings
        yield Footer(id="footer")
    
    def on_path_selected(self, message: PathSelected) -> None:
        """
        处理Browser发出的路径选择消息，更新对应的输入框
        
        Args:
            message: 路径选择消息
        """
        if not message.browser_id:
            return
        
        path_str = str(message.path)
        if message.browser_id == "source_browser":
            self.query_one("#source", Input).value = path_str
        elif message.browser_id == "target_browser":
            self.query_one("#target", Input).value = path_str
        
        # 更新命令预览
        self.update_preview()

    def on_select_path_requested(self, message: SelectPathRequested) -> None:
        if not message.browser_id:
            return
        
        path_str = str(message.path)
        if message.browser_id == "source_browser":
            self.query_one("#source", Input).value = path_str
        elif message.browser_id == "target_browser":
            self.query_one("#target", Input).value = path_str
        
        # 更新命令预览
        self.update_preview()
    
    def on_option_selected(self, message: OptionSelected) -> None:
        """
        处理OptionsPanel发出的选项选中消息，更新描述显示
        
        Args:
            message: 选项选中消息
        """
        desc_widget = self.query_one("#desc", Static)
        desc_widget.update(message.description)
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """
        处理输入框内容变化事件
        
        Args:
            event: 输入变化事件
        """
        self.update_preview()
    
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """
        处理复选框状态变化事件
        
        Args:
            event: 复选框变化事件
        """
        self.update_preview()
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """
        处理输入框提交事件
        
        如果是value_options的编辑输入框，转发给ValueOptionsPanel处理。
        如果是cmd_input，发送到运行的进程。
        
        Args:
            event: 输入提交事件
        """
        if event.input.id == "value_edit_input":
            # 转发给ValueOptionsPanel处理
            try:
                value_opts = self.query_one("#value_options", ValueOptionsPanel)
                value_opts.on_input_submitted(event)
                # 确保更新preview
                self.update_preview()
            except:
                pass
        elif event.input.id == "cmd_input":
            # 发送输入到运行的进程
            user_input = event.input.value.strip()
            if user_input:
                from backend.command_executor import CommandExecutor
                if CommandExecutor.send_input(user_input):
                    log_widget = self.query_one("#logs", RichLog)
                    log_widget.write(f"[dim]Sent: {user_input}[/dim]")
                event.input.value = ""  # 清空输入框
    
    def update_preview(self) -> None:
        """
        更新命令预览
        
        收集所有选中的选项和路径，构建完整的rsync命令并更新预览显示。
        """
        src = self.query_one("#source", Input).value
        dest = self.query_one("#target", Input).value
        
        # 收集所有选中的选项
        short_options = []
        long_options = []
        value_options = []
        
        # 从short_options获取选中的选项
        try:
            short_opts = self.query_one("#short_options", OptionsPanel)
            short_options = short_opts.get_selected_options()
        except:
            pass
        
        # 从long_options获取选中的选项
        try:
            long_opts = self.query_one("#long_options", OptionsPanel)
            long_options = long_opts.get_selected_options()
        except:
            pass
        
        # 从value_options获取选中的选项（带值）
        try:
            value_opts = self.query_one("#value_options", ValueOptionsPanel)
            value_options = value_opts.get_selected_options()
        except:
            pass
        
        # 使用命令构建器构建命令
        cmd = RsyncCommandBuilder.build_command(
            source_path=src,
            target_path=dest,
            short_options=short_options if short_options else None,
            long_options=long_options if long_options else None,
            value_options=value_options if value_options else None
        )
        
        # 更新预览显示
        self.query_one("#preview", CommandPreview).update(cmd)
    
    def on_command_execute_request(self, message: CommandExecuteRequest) -> None:
        """
        处理命令执行请求
        
        异步执行rsync命令并将输出写入日志。
        
        Args:
            message: 命令执行请求消息
        """
        log_widget = self.query_one("#logs", RichLog)
        cmd_input = self.query_one("#cmd_input", Input)
        
        # 记录执行的命令
        log_widget.write(f"[cyan]Executing {message.command}[/cyan]")
        
        # 启用输入框
        cmd_input.disabled = False
        cmd_input.placeholder = "Enter input for running process (press Enter to send)..."
        
        # 异步执行命令
        asyncio.create_task(
            self._execute_command(message.command, log_widget, cmd_input)
        )
    
    async def _execute_command(self, command: str, log_widget: RichLog, cmd_input: Input) -> None:
        """
        异步执行命令并将输出写入日志
        
        Args:
            command: 要执行的命令字符串
            log_widget: 日志显示组件
            cmd_input: 命令输入框组件
        """
        def on_stdout(line: str) -> None:
            """标准输出回调"""
            log_widget.write(f"[green]{line}[/green]")
        
        def on_stderr(line: str) -> None:
            """标准错误回调"""
            log_widget.write(f"[yellow]{line}[/yellow]")
        
        def on_complete(exit_code: int) -> None:
            """完成回调"""
            if exit_code == 0:
                log_widget.write(f"[cyan]Command completed successfully (exit code: {exit_code})[/cyan]")
            else:
                log_widget.write(f"[red]Command failed with exit code: {exit_code}[/red]")
            
            # 禁用输入框
            cmd_input.disabled = True
            cmd_input.placeholder = "No process running..."
        
        # 使用命令执行器执行命令
        await CommandExecutor.execute_command(
            command=command,
            on_stdout=on_stdout,
            on_stderr=on_stderr,
            on_complete=on_complete
        )
    
    def on_mount(self) -> None:
        """应用挂载时的初始化操作"""
        # 确保Header显示标题
        header = self.query_one("#header", Header)
        if not header.tall:
            header.tall = False
        
        # 初始化日志
        self.query_one(RichLog).write("System ready.")
    
    def on_focus(self, event) -> None:
        """当任何组件获得焦点时，更新Footer显示快捷键"""
        # Textual的Footer会自动显示当前聚焦组件的绑定
        # 我们只需要确保Footer能够正确更新
        # Footer组件会自动处理绑定显示，所以这里不需要额外操作
        pass


def main():
    """应用程序入口点"""
    app = LazySyncUI(watch_css=True)
    app.run()


if __name__ == "__main__":
    main()
