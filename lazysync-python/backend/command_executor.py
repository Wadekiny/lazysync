"""
命令执行器模块
负责执行rsync命令并处理输出
"""

import asyncio
import shlex
import pexpect
import threading
import queue
from typing import Callable, Optional
from utils.logger import log


class AsyncPexpect:
    """将 pexpect 包装为异步接口"""
    
    def __init__(self, command, encoding="utf-8"):
        """
        初始化异步 pexpect
        
        Args:
            command: 要执行的命令（字符串或列表）
            encoding: 编码格式
        """
        if isinstance(command, str):
            # 如果是字符串，需要解析为列表
            parts = shlex.split(command)
            self.child = pexpect.spawn(parts[0], args=parts[1:], encoding=encoding)
        else:
            # 如果是列表，直接使用
            self.child = pexpect.spawn(command[0], args=command[1:], encoding=encoding)
        
        self.output_queue = queue.Queue()
        self.running = True
        self.read_thread = None
        
    def _read_output(self):
        """在后台线程中读取输出"""
        while self.running:
            try:
                # 检查进程是否还活着
                if not self.child.isalive():
                    # 读取剩余输出
                    try:
                        remaining = self.child.read_nonblocking(size=4096, timeout=0)
                        if remaining:
                            self.output_queue.put(("output", remaining))
                    except (pexpect.EOF, pexpect.TIMEOUT):
                        pass
                    self.output_queue.put(("eof", None))
                    break
                
                # 使用 read_nonblocking 读取新数据，避免重复读取
                try:
                    data = self.child.read_nonblocking(size=4096, timeout=0.1)
                    if data:
                        # 将新读取的数据放入队列
                        self.output_queue.put(("output", data))
                except pexpect.TIMEOUT:
                    # 超时是正常的，继续循环
                    continue
                except pexpect.EOF:
                    # 进程结束，读取剩余数据
                    try:
                        remaining = self.child.read_nonblocking(size=4096, timeout=0)
                        if remaining:
                            self.output_queue.put(("output", remaining))
                    except:
                        pass
                    self.output_queue.put(("eof", None))
                    break
            except (pexpect.ExceptionPexpect, pexpect.EOF):
                self.output_queue.put(("eof", None))
                break
    
    async def expect(self, patterns, timeout=None):
        """
        异步等待模式匹配
        
        Args:
            patterns: 要匹配的模式列表
            timeout: 超时时间（秒）
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, 
            lambda: self.child.expect(patterns, timeout=timeout)
        )
    
    def sendline(self, line):
        """发送一行数据"""
        if self.child and self.child.isalive():
            self.child.sendline(line)
    
    def send(self, data):
        """发送数据"""
        if self.child and self.child.isalive():
            self.child.send(data)
    
    async def read_output(self):
        """异步读取输出"""
        # 启动后台线程（如果还没启动）
        if self.read_thread is None or not self.read_thread.is_alive():
            self.read_thread = threading.Thread(target=self._read_output, daemon=True)
            self.read_thread.start()
        
        # 从队列中获取输出（非阻塞）
        try:
            event_type, data = self.output_queue.get_nowait()
            return event_type, data
        except queue.Empty:
            # 如果没有数据，等待一小段时间
            await asyncio.sleep(0.01)
            return None, None
    
    def isalive(self):
        """检查进程是否还在运行"""
        return self.child.isalive() if self.child else False
    
    def close(self):
        """关闭进程"""
        self.running = False
        if self.child and self.child.isalive():
            self.child.close()
    
    def wait(self):
        """等待进程结束"""
        if self.child:
            return self.child.wait()


class CommandExecutor:
    """
    命令执行器
    
    负责异步执行命令并将输出传递给回调函数。
    使用 pexpect 来支持交互式命令执行。
    """
    
    _current_process: Optional[AsyncPexpect] = None
    
    @staticmethod
    async def execute_command(
        command: str,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        on_complete: Optional[Callable[[int], None]] = None
    ) -> int:
        """
        异步执行命令（使用 pexpect）
        
        Args:
            command: 要执行的命令字符串
            on_stdout: 标准输出回调函数，接收输出行
            on_stderr: 标准错误回调函数，接收错误行
            on_complete: 完成回调函数，接收退出码
            
        Returns:
            命令的退出码
        """
        try:
            # 解析命令
            parts = shlex.split(command)
            if not parts:
                if on_stderr:
                    on_stderr("Error: Empty command")
                return 1
            
            # 创建 pexpect 进程
            CommandExecutor._current_process = AsyncPexpect(command, encoding="utf-8")
            
            # 记录命令开始执行
            log(f"Executing command: {command}")
            
            # 持续读取输出直到进程结束
            while CommandExecutor._current_process.isalive():
                event_type, data = await CommandExecutor._current_process.read_output()
                if event_type == "output":
                    # 将输出写入回调（pexpect 会同时捕获 stdout 和 stderr）
                    if data:
                        # 记录到日志文件
                        log(f"Output: {data}")
                        if on_stdout:
                            _write_output(data, on_stdout)
                elif event_type == "eof":
                    break
                await asyncio.sleep(0.01)
            
            # 等待进程结束并获取退出码
            exit_code = CommandExecutor._current_process.wait()
            
            # 处理剩余的输出
            while True:
                event_type, data = await CommandExecutor._current_process.read_output()
                if event_type == "output" and data:
                    # 记录到日志文件
                    log(f"Output: {data}")
                    if on_stdout:
                        _write_output(data, on_stdout)
                elif event_type == "eof":
                    break
                await asyncio.sleep(0.01)
            
            # 记录退出码
            log(f"Command completed with exit code: {exit_code}")
            if on_complete:
                on_complete(exit_code)
            
            # 清理
            CommandExecutor._current_process.close()
            CommandExecutor._current_process = None
            
            return exit_code if exit_code is not None else 0
            
        except FileNotFoundError:
            cmd_name = command.split()[0] if command.split() else 'unknown'
            if on_stderr:
                on_stderr(f"Error: Command not found: {cmd_name}")
            return 127
        except Exception as e:
            if on_stderr:
                on_stderr(f"Error executing command: {str(e)}")
            if CommandExecutor._current_process:
                CommandExecutor._current_process.close()
                CommandExecutor._current_process = None
            return 1
    
    @staticmethod
    def send_input(line: str) -> bool:
        """
        向当前运行的进程发送输入
        
        Args:
            line: 要发送的输入行
            
        Returns:
            是否成功发送（如果进程不存在则返回 False）
        """
        if CommandExecutor._current_process and CommandExecutor._current_process.isalive():
            CommandExecutor._current_process.sendline(line)
            log(f"Sent input to process: {line}")
            return True
        return False
    
    @staticmethod
    def has_running_process() -> bool:
        """
        检查是否有正在运行的进程
        
        Returns:
            是否有正在运行的进程
        """
        return CommandExecutor._current_process is not None and CommandExecutor._current_process.isalive()


def _write_output(text: str, callback: Callable[[str], None]) -> None:
    """
    辅助函数：将输出写入回调，正确处理换行
    
    Args:
        text: 输出文本
        callback: 回调函数，接收每一行
    """
    if not text:
        return
    
    # 使用splitlines()分割，它会正确处理各种换行符（\n, \r\n, \r）
    # keepends=False会移除换行符，但保留空行（作为空字符串）
    lines = text.splitlines(keepends=False)
    
    # 如果输出以换行符结尾，splitlines会移除最后的空行
    # 我们需要恢复这个空行（如果原始输出确实以换行符结尾）
    if text.endswith('\n') or text.endswith('\r\n') or text.endswith('\r'):
        # 如果最后一行不为空，说明原始输出在最后一行后有换行符
        # 我们需要添加一个空行来保持格式
        if not lines or (lines and lines[-1]):
            lines.append('')
    
    # 调用回调函数写入每一行
    for line in lines:
        callback(line)
