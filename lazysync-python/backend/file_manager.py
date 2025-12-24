"""
文件管理器模块
负责本地和远程文件系统的操作，与UI渲染无关
实现前后端分离的数据层
"""

import os
import subprocess
import socket
from pathlib import Path
from typing import List, Tuple, Optional, Union
import asyncssh
from asyncssh import SSHClientConnection
from pathlib import PurePosixPath
from utils.logger import log

# 导入 rfb_client（必需）
try:
    import rfb_client
except ImportError:
    raise ImportError(
        "rfb_client module not found. Please build it first:\n"
        "  cd lazysync-client && maturin develop"
    )


class LocalFileManager:
    """
    本地文件系统管理器
    
    负责处理所有本地文件系统的数据操作，与UI渲染无关。
    这是实现"前后端分离"的数据模块。
    """
    
    def __init__(self, initial_path: Union[Path, str]):
        """
        初始化本地文件管理器
        
        Args:
            initial_path: 初始路径
        """
        self._current_path = Path(initial_path).resolve()
    
    @property
    def current_path(self) -> Path:
        """
        获取当前目录的Path对象
        
        Returns:
            当前目录的Path对象
        """
        return self._current_path
    
    def get_contents(self, show_hidden: bool = False) -> List[Tuple[str, Path]]:
        """
        获取当前目录的内容列表
        
        目录在前，文件在后，并按名称排序。
        
        Args:
            show_hidden: 是否显示隐藏文件和目录
            
        Returns:
            格式：[(显示名称, 路径对象), ...]
            如果遇到权限错误，返回错误提示项
        """
        items: List[Path] = []
        try:
            items = list(self._current_path.iterdir())
        except PermissionError:
            return [("<< Permission Denied >>", self._current_path)]
        
        # 过滤隐藏文件
        if not show_hidden:
            items = [p for p in items if not p.name.startswith('.')]
        
        # 排序：先目录，后文件；然后按名称字母顺序排序
        dirs = sorted([p for p in items if p.is_dir()])
        files = sorted([p for p in items if p.is_file()])
        
        contents = []
        # 添加父目录标识，用于UI显示
        contents.append(("../", self._current_path.parent))
        
        # 目录用 / 结尾
        for p in dirs:
            contents.append((f"{p.name}/", p))
        # 文件不需要 / 结尾
        for p in files:
            contents.append((p.name, p))
        
        return contents
    
    def change_dir(self, target_path: Union[Path, str]) -> bool:
        """
        尝试更改当前目录
        
        Args:
            target_path: 目标路径
            
        Returns
            如果成功则返回True，否则返回False
        """
        new_path = Path(target_path).resolve()
        if new_path.is_dir():
            self._current_path = new_path
            return True
        return False

    def change_parent(self):
        new_path = self.current_path.parent
        return self.change_dir(new_path)


class SSHFileManager:
    """
    远程SSH文件系统管理器（使用 Rust server）
    
    负责处理所有远程SSH文件系统的数据操作，与UI渲染无关。
    通过 Rust server 和端口转发来获取远程文件信息。
    """
    
    def __init__(self):
        """初始化SSH文件管理器"""
        self.conn: Optional[SSHClientConnection] = None
        self._current_path = "."
        self.client: Optional[object] = None  # rfb_client.PyClient
        self.local_port: Optional[int] = None  # 本地端口转发端口
        self.port_forward_listener = None  # asyncssh 端口转发监听器
        self.port_forward_process: Optional[subprocess.Popen] = None  # 后备方案：subprocess
        self.server_path = ""  # 将在部署时设置为绝对路径
        self.server_pid: Optional[int] = None
        self.ssh_host: Optional[str] = None  # SSH 主机地址
        self.ssh_port: int = 22  # SSH 端口
        self.ssh_username: Optional[str] = None  # SSH 用户名
    
    async def connect(self, **kwargs) -> None:
        """
        连接到SSH服务器并设置 Rust server
        
        Args:
            **kwargs: asyncssh.connect()的参数
                - host: 主机地址
                - port: 端口号
                - username: 用户名
                - client_factory: SSH客户端工厂函数
                - known_hosts: 已知主机配置
        """
        # 1. 建立 SSH 连接
        # self.conn = await asyncssh.connect(**kwargs)
        
        # 保存连接信息用于后续操作
        self.ssh_host = kwargs.get("host", "localhost")
        self.ssh_port = kwargs.get("port", 22)
        self.ssh_username = kwargs.get("username", "user")
        
        # 2. 检查并启动远程 Rust server
        # await self._ensure_remote_server()
        # log(f"ensure_remote_server: {self.ssh_host}, {self.ssh_port}, {self.ssh_username}")
        
        # 3. 设置端口转发
        # await self._setup_port_forward(self.ssh_host, self.ssh_port)
        # log(f"setup_port_forward: {self.ssh_host}, {self.ssh_port}")
        
        # 4. 创建本地 Rust client 连接到转发的端口
        await self._connect_client()
        log("connect_client")
        
        # 5. 获取远程HOME目录作为初始路径
        # home_result = await self.conn.run("echo $HOME")
        # self._current_path = home_result.stdout.strip()
        self._current_path = "/home"
        log(f"Initial path set to: {self._current_path}")
    
    async def _ensure_remote_server(self) -> None:
        """确保远程 Rust server 正在运行"""
        # 检查 server 是否在运行（通过检查端口 9000）
        result = await self.conn.run("netstat -tuln 2>/dev/null | grep :9000 || ss -tuln 2>/dev/null | grep :9000 || echo 'not_running'")
        
        server_running = ":9000" in result.stdout and "not_running" not in result.stdout
        
        if not server_running:
            log("Remote server not running, deploying...")
            await self._deploy_server()
            await self._start_server()
        else:
            log("Remote server is already running")
    
    async def _deploy_server(self) -> None:
        """部署 Rust server 到远程服务器"""
        # 检测远程服务器架构
        arch_result = await self.conn.run("uname -m")
        remote_arch = arch_result.stdout.strip().lower()
        os_result = await self.conn.run("uname -s")
        remote_os = os_result.stdout.strip().lower()
        
        log(f"Remote server: OS={remote_os}, Arch={remote_arch}")
        
        # 检测本地架构
        import platform
        local_arch = platform.machine().lower()
        local_os = platform.system().lower()
        
        log(f"Local machine: OS={local_os}, Arch={local_arch}")
        
        # 检查架构是否匹配
        arch_mapping = {
            'x86_64': ['x86_64', 'amd64'],
            'aarch64': ['aarch64', 'arm64'],
            'arm64': ['aarch64', 'arm64'],
        }
        
        local_arch_normalized = arch_mapping.get(local_arch, [local_arch])[0]
        remote_arch_normalized = next((k for k, v in arch_mapping.items() if remote_arch in v), remote_arch)
        
        if local_os != remote_os or local_arch_normalized != remote_arch_normalized:
            raise RuntimeError(
                f"Architecture mismatch detected!\n"
                f"  Local: {local_os}/{local_arch}\n"
                f"  Remote: {remote_os}/{remote_arch}\n\n"
                f"Please build the server for the remote architecture:\n"
                f"  1. Cross-compile: cd lazysync-server && cargo build --release --target <target-triple>\n"
                f"  2. Or build on remote: ssh to server and run 'cd lazysync-server && cargo build --release'\n"
                f"     Then download the binary from remote server."
            )
        
        # 获取本地 server 可执行文件路径
        # 假设在项目根目录的 lazysync-server/target/release/rfb_server
        project_root = Path(__file__).parent.parent.parent
        local_server_path = project_root / "lazysync-server" / "target" / "release" / "rfb_server"
        
        if not local_server_path.exists():
            # 尝试其他可能的位置
            local_server_path = project_root / "lazysync-server" / "target" / "debug" / "rfb_server"
            if not local_server_path.exists():
                raise FileNotFoundError(
                    f"Rust server executable not found. Please build it first:\n"
                    f"  cd lazysync-server && cargo build --release"
                )
        
        # 获取远程 HOME 目录的绝对路径
        home_result = await self.conn.run("echo $HOME")
        remote_home = home_result.stdout.strip()
        remote_dir = f"{remote_home}/.lazysync"
        remote_path = f"{remote_dir}/rfb_server"
        
        # 创建远程目录
        await self.conn.run(f"mkdir -p {remote_dir}")
        
        log(f"Uploading server to {remote_path}...")
        
        # 使用已建立的 SSH 连接的 SFTP 功能上传文件
        # 这样可以避免使用 subprocess scp 导致的密码输入问题
        sftp = await self.conn.start_sftp_client()
        try:
            # 使用 SFTP put 方法上传文件
            await sftp.put(str(local_server_path), remote_path)
            log(f"File uploaded successfully to {remote_path}")
        finally:
            # 关闭 SFTP 客户端
            sftp.exit()
        
        # 设置可执行权限
        await self.conn.run(f"chmod +x {remote_path}")
        
        # 验证文件是否可以执行（检查文件类型）
        file_check = await self.conn.run(f"file {remote_path}")
        log(f"Remote file type: {file_check.stdout.strip()}")
        
        # 更新 server_path 为绝对路径
        self.server_path = remote_path
        
        log("Server deployed successfully")
    
    async def _start_server(self) -> None:
        """在远程启动 Rust server"""
        if not self.server_path:
            raise RuntimeError("Server path not set. Deploy server first.")
        
        # 获取远程 HOME 目录的绝对路径（用于日志文件）
        home_result = await self.conn.run("echo $HOME")
        remote_home = home_result.stdout.strip()
        log_file = f"{remote_home}/.lazysync/rfb_server.log"
        
        # 使用 nohup 在后台运行 server
        # 重定向输出到日志文件
        cmd = f"nohup {self.server_path} > {log_file} 2>&1 &"
        
        result = await self.conn.run(cmd)
        
        # 等待一下确保 server 启动
        import asyncio
        await asyncio.sleep(1)
        
        # 检查 server 是否成功启动（检查端口是否被监听）
        check_result = await self.conn.run("netstat -tuln 2>/dev/null | grep :9000 || ss -tuln 2>/dev/null | grep :9000 || echo 'not_running'")
        if "not_running" in check_result.stdout or ":9000" not in check_result.stdout:
            # 也检查进程
            proc_check = await self.conn.run("pgrep -f rfb_server || echo 'not_found'")
            if "not_found" in proc_check.stdout:
                raise RuntimeError("Failed to start remote server. Check log file for details.")
        
        log("Remote server started successfully")
    
    async def _setup_port_forward(self, host: str, port: int) -> None:
        """设置 SSH 端口转发（本地端口 -> 远程 9000）"""
        # 找到一个可用的本地端口
        # self.local_port = self._find_free_port()
        self.local_port = 9000
        
        log(f"Setting up port forward: localhost:{self.local_port} -> remote:127.0.0.1:9000")
        
        # 使用 asyncssh 的本地端口转发功能
        # forward_local_port 创建一个本地监听器，将连接转发到远程地址
        try:
            # 创建本地端口转发
            # 参数: (listen_host, listen_port, dest_host, dest_port)
            # listen_host: 本地监听的主机地址，'' 表示监听所有接口
            # listen_port: 本地监听的端口号
            # dest_host: 远程服务器上的目标地址（127.0.0.1 表示远程服务器本地）
            # dest_port: 远程服务器上的目标端口号
            self.port_forward_listener = await self.conn.forward_local_port(
                '',  # 监听所有接口
                self.local_port,
                '127.0.0.1',  # 远程服务器上的地址
                9000  # 远程服务器上的端口
            )
            log(f"Port forward established on localhost:{self.local_port}")
        except AttributeError as e:
            # asyncssh 版本可能不同，尝试其他方法
            log(f"error: {e}")
            log("forward_local_port not available, using fallback method")
            await self._setup_port_forward_fallback(host, port)
        except Exception as e:
            log(f"Failed to establish port forward using asyncssh: {e}")
            # 后备方案：使用 subprocess 启动 SSH 端口转发
            await self._setup_port_forward_fallback(host, port)
    
    def _find_free_port(self) -> int:
        """找到一个可用的本地端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port
    
    async def _setup_port_forward_fallback(self, host: str, port: int) -> None:
        """后备方案：使用 subprocess 启动 SSH 端口转发"""
        # 使用 SSH 端口转发
        # ssh -L local_port:127.0.0.1:9000 user@host -N
        username = self.conn.get_extra_info('username', 'user')
        ssh_cmd = [
            "ssh",
            "-N",  # 不执行远程命令
            "-L", f"{self.local_port}:127.0.0.1:9000",  # 本地端口转发
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-p", str(port),
            f"{username}@{host}",
        ]
        
        log(f"Using fallback SSH port forwarding method")
        
        # 启动端口转发进程
        self.port_forward_process = subprocess.Popen(
            ssh_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        
        # 等待端口转发建立
        import asyncio
        for _ in range(10):  # 最多等待 1 秒
            if self._is_port_open(self.local_port):
                log(f"Port forward established on localhost:{self.local_port}")
                return
            await asyncio.sleep(0.1)
        
        raise RuntimeError("Failed to establish port forward")
    
    def _is_port_open(self, port: int) -> bool:
        """检查端口是否开放"""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                result = s.connect_ex(('127.0.0.1', port))
                return result == 0
        except:
            return False
    
    async def _connect_client(self) -> None:
        """创建本地 Rust client 连接到转发的端口"""
        self.local_port = 9000
        if self.local_port is None:
            raise RuntimeError("Port forward not established")
        
        # 创建 PyClient 连接到本地转发的端口
        self.client = rfb_client.PyClient(f"127.0.0.1:{self.local_port}")
        log("Connected to remote server via Rust client")
    
    @property
    def current_path(self) -> str:
        """
        获取当前远程路径
        
        Returns:
            当前路径字符串
        """
        return self._current_path
    
    async def change_dir(self, target_path: str) -> bool:
        """
        尝试更改当前远程目录
        
        Args:
            target_path: 目标路径（可以是绝对路径或相对路径）
            
        Returns:
            如果成功则返回True，否则返回False
        """
        try:
            new_path = (
                PurePosixPath(self._current_path) / target_path
                if not target_path.startswith("/")
                else PurePosixPath(target_path)
            )
            
            # 使用 Rust client 检查路径是否存在
            if not self.client:
                raise RuntimeError("Rust client not connected")
            
            # 先尝试获取路径信息，如果成功则说明路径存在
            entries = self.client.get_path(str(new_path))
            if entries is not None:
                self._current_path = str(new_path)
                return True
            
        except Exception as e:
            log(f"Error changing directory: {e}")
            return False
        
        return False
    
    def get_contents(self, show_hidden: bool = False) -> List[Tuple[str, str]]:
        """
        获取当前远程目录的内容列表

        返回格式：
            [(显示名称, 绝对路径), ...]

        - 目录显示名以 / 结尾
        - 文件不带 /
        - 父目录显示为 ../
        """
        if not self.client:
            raise RuntimeError(
                "Rust client not connected. Please ensure SSH connection is established first."
            )
        
        try:
            # 使用 Rust client 获取文件列表
            log(f"Getting contents for path: {self._current_path}")
            log(f"Client status: {self.client is not None}")
            log(f"Local port: {self.local_port}")
            
            entries = self.client.get_path(self._current_path)
            log(f"Received {len(entries) if entries else 0} entries from Rust client")
            
            if entries is None:
                log("Warning: get_path returned None")
                return []
            
            if len(entries) == 0:
                log(f"Warning: get_path returned empty list for path: {self._current_path}")
                # 尝试检查路径是否存在
                log("This might indicate the path doesn't exist or is empty")
            
            current = PurePosixPath(self._current_path)
            dirs: List[Tuple[str, str]] = []
            files: List[Tuple[str, str]] = []
            
            for entry in entries:
                if not isinstance(entry, dict):
                    log(f"Warning: entry is not a dict: {type(entry)}, value: {entry}")
                    continue
                    
                name = entry.get('name', '')
                is_dir = entry.get('is_dir', False)
                
                if name in (".", ".."):
                    continue
                
                if not show_hidden and name.startswith("."):
                    continue
                
                abs_path = str(current / name)
                
                if is_dir:
                    dirs.append((f"{name}/", abs_path))
                else:
                    files.append((name, abs_path))
            
            log(f"Processed {len(dirs)} directories and {len(files)} files")
            
            # 排序
            dirs.sort(key=lambda x: x[0])
            files.sort(key=lambda x: x[0])
            
            contents: List[Tuple[str, str]] = []
            
            # 父目录（如果不是根目录）
            if str(current) != "/":
                parent = current.parent
                contents.append(("../", str(parent)))
            
            contents.extend(dirs)
            contents.extend(files)
            
            return contents
            
        except Exception as e:
            log(f"Error getting contents via Rust client: {e}")
            import traceback
            log(f"Traceback: {traceback.format_exc()}")
            raise
    
    async def close(self) -> None:
        """关闭SSH连接和清理资源"""
        # 关闭 Rust client
        if self.client:
            # PyClient 没有显式的 close 方法，但我们可以删除引用
            self.client = None
        
        # 关闭端口转发监听器
        if self.port_forward_listener:
            try:
                self.port_forward_listener.close()
            except:
                pass
            self.port_forward_listener = None
        
        # 关闭端口转发进程（后备方案）
        if self.port_forward_process:
            self.port_forward_process.terminate()
            self.port_forward_process.wait()
            self.port_forward_process = None
        
        # 关闭 SSH 连接
        if self.conn:
            self.conn.close()
            await self.conn.wait_closed()

    async def change_parent(self) -> bool:
        """
        返回父目录

        Returns:
            如果成功则返回 True，否则返回 False
        """
        current = PurePosixPath(self._current_path)
        parent = current.parent

        # 如果已经是根目录，不做任何操作
        if str(current) == "/":
            return False

        return await self.change_dir(str(parent))
