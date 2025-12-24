#!/usr/bin/env python3
"""
Python客户端示例，直接调用Rust函数（使用PyO3绑定）
"""

import sys
import asyncio
import threading
import getpass
import os
import time

try:
    import rfb_client
except ImportError:
    print("Error: rfb_client module not found.")
    print("Please build the Python extension first:")
    print("  cd lazysync-client")
    print("  maturin develop  # or: maturin build")
    sys.exit(1)


# 端口转发模式："asyncssh"（默认异步库）/"paramiko"（同步库，支持密码）/"none"
FORWARD_MODE = None
# FORWARD_MODE = "paramiko"
# SSH服务器信息（开启端口转发后生效）
SSH_HOST = "116.172.93.227"
SSH_PORT = 29293
SSH_USER = "ubuntu"
SSH_PASSWORD = None  # 可改为密码字符串，或使用SSH_KEY_PATH；也可用环境变量 LAZYSYNC_SSH_PASSWORD
SSH_KEY_PATH = None  # 例如: "/home/user/.ssh/id_rsa"；也可用环境变量 LAZYSYNC_SSH_KEY_PATH
TUNNEL_READY_DELAY_SEC = 1.0  # 转发就绪后等待一会再连接 client
CLIENT_CONNECT_RETRIES = 5  # client 连接重试次数
CLIENT_CONNECT_RETRY_DELAY_SEC = 0.5  # 每次重试等待时间
# 远端服务地址与本地端口转发
REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = 9000
LOCAL_FORWARD_HOST = "127.0.0.1"
LOCAL_FORWARD_PORT = 9000


def format_size(size: int) -> str:
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def print_entry_info(entry: dict) -> None:
    """打印单个文件/目录的详细信息"""
    name = entry.get('name', '')
    is_dir = entry.get('is_dir', False)
    size = entry.get('size', 0)
    permissions = entry.get('permissions', '')
    modified = entry.get('modified', '')
    
    # 格式化显示
    size_str = format_size(size) if not is_dir else '-'
    
    print(f"  {permissions:10} {modified:19} {size_str:>10} {name}")


def run_client(host: str, port: int) -> None:
    # 1. 创建client对象
    print("Creating client and connecting to server...")
    last_err = None
    for attempt in range(1, CLIENT_CONNECT_RETRIES + 1):
        try:
            client = rfb_client.PyClient(f"{host}:{port}")
            print("Connected successfully!")
            break
        except Exception as e:
            last_err = e
            if attempt < CLIENT_CONNECT_RETRIES:
                time.sleep(CLIENT_CONNECT_RETRY_DELAY_SEC)
            else:
                raise
    print()

    # 2. 调用client的函数得到指定路径下的文件信息
    # 默认示例路径：较小的目录，避免扫描过大目录导致超时
    path_request = "/home/ubuntu/.config/nvim"
    print(f"Getting path data for: {path_request}")

    try:
        entries = client.get_path(path_request)
        print(f"Entries count: {len(entries)}")
        print()

        # 显示所有文件和目录的详细信息
        if entries:
            print(f"All entries in {path_request}:")
            print(f"{'Permissions':<10} {'Modified':<19} {'Size':>10} {'Name'}")
            print("-" * 80)
            for entry in entries:
                print_entry_info(entry)
        else:
            print("  (no entries found)")

        # 示例2: 再次请求相同路径（应该从cache返回）
        print()
        print(f"Getting path data again (should be from cache): {path_request}")
        entries2 = client.get_path(path_request)
        print(f"Entries count: {len(entries2)}")

        # 示例3: 只获取目录
        print()
        print("Directories only:")
        dirs = [e for e in entries if e.get('is_dir', False)]
        for d in dirs:
            print(f"  {d['name']}")

    except Exception as e:
        print(f"Error: {e}")


def _build_connect_kwargs():
    try:
        import asyncssh  # noqa: F401
    except ImportError:
        print("Error: asyncssh module not found.")
        print("Please install it first:")
        print("  pip install asyncssh")
        sys.exit(1)

    env_password = os.getenv("LAZYSYNC_SSH_PASSWORD")
    env_key_path = os.getenv("LAZYSYNC_SSH_KEY_PATH")

    connect_kwargs = {
        "host": SSH_HOST,
        "port": SSH_PORT,
        "username": SSH_USER,
    }
    if env_password:
        connect_kwargs["password"] = env_password
    elif SSH_PASSWORD:
        connect_kwargs["password"] = SSH_PASSWORD
    if env_key_path:
        connect_kwargs["client_keys"] = [env_key_path]
    elif SSH_KEY_PATH:
        connect_kwargs["client_keys"] = [SSH_KEY_PATH]
    if "password" not in connect_kwargs and "client_keys" not in connect_kwargs:
        # 没有预设密码或密钥时可临时输入密码；直接回车则尝试本地默认密钥/agent
        if sys.stdin.isatty():
            typed = getpass.getpass(
                "未设置SSH_PASSWORD或SSH_KEY_PATH，如需密码登录请输入（留空则使用默认密钥/agent）: "
            )
            if typed:
                connect_kwargs["password"] = typed
        else:
            print("未设置SSH_PASSWORD或SSH_KEY_PATH，且当前无交互输入；将尝试默认密钥/agent。")
    return connect_kwargs


async def run_with_ssh_tunnel() -> None:
    import asyncssh

    print("Creating SSH tunnel with asyncssh...")
    connect_kwargs = _build_connect_kwargs()

    async with asyncssh.connect(**connect_kwargs) as conn:
        listener = await conn.forward_local_port(
            LOCAL_FORWARD_HOST,
            LOCAL_FORWARD_PORT,
            REMOTE_HOST,
            REMOTE_PORT,
        )
        print(
            "SSH tunnel ready: "
            f"{LOCAL_FORWARD_HOST}:{LOCAL_FORWARD_PORT} -> {REMOTE_HOST}:{REMOTE_PORT}"
        )
        try:
            await asyncio.to_thread(run_client, LOCAL_FORWARD_HOST, LOCAL_FORWARD_PORT)
        finally:
            listener.close()
            await listener.wait_closed()


def start_asyncssh_tunnel_sync():
    """同步方式启动 asyncssh 端口转发：后台线程运行事件循环，主线程同步返回。"""
    import asyncssh

    connect_kwargs = _build_connect_kwargs()
    loop = asyncio.new_event_loop()
    state = {}

    def loop_runner():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=loop_runner, daemon=True)
    thread.start()

    async def open_tunnel():
        conn = await asyncssh.connect(**connect_kwargs)
        listener = await conn.forward_local_port(
            LOCAL_FORWARD_HOST,
            LOCAL_FORWARD_PORT,
            REMOTE_HOST,
            REMOTE_PORT,
        )
        state["conn"] = conn
        state["listener"] = listener
        print(
            "SSH tunnel ready: "
            f"{LOCAL_FORWARD_HOST}:{LOCAL_FORWARD_PORT} -> {REMOTE_HOST}:{REMOTE_PORT}"
        )

    try:
        fut = asyncio.run_coroutine_threadsafe(open_tunnel(), loop)
        fut.result(timeout=15)
    except Exception:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        raise

    def close_tunnel():
        async def _close():
            listener = state.get("listener")
            conn = state.get("conn")
            if listener:
                listener.close()
                await listener.wait_closed()
            if conn:
                conn.close()
            loop.stop()

        asyncio.run_coroutine_threadsafe(_close(), loop).result(timeout=10)
        thread.join(timeout=2)

    return close_tunnel


def start_paramiko_tunnel_sync():
    """使用 paramiko 的同步端口转发（支持密码登录）。"""
    try:
        import paramiko
    except ImportError:
        print("Error: paramiko module not found.")
        print("Please install it first:")
        print("  pip install paramiko")
        sys.exit(1)

    env_password = os.getenv("LAZYSYNC_SSH_PASSWORD")
    env_key_path = os.getenv("LAZYSYNC_SSH_KEY_PATH")

    password = env_password or SSH_PASSWORD
    key_filename = env_key_path or SSH_KEY_PATH
    if not password and not key_filename:
        if sys.stdin.isatty():
            typed = getpass.getpass("未设置SSH_PASSWORD或SSH_KEY_PATH，如需密码登录请输入（留空尝试默认密钥/agent）: ")
            if typed:
                password = typed
        else:
            print("未设置SSH_PASSWORD或SSH_KEY_PATH，且当前无交互输入；将尝试默认密钥/agent。")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        SSH_HOST,
        port=SSH_PORT,
        username=SSH_USER,
        password=password,
        key_filename=key_filename,
    )

    transport = client.get_transport()
    stop_event = threading.Event()
    ready_event = threading.Event()
    error_holder = {}

    def _forward():
        forward_tunnel(
            LOCAL_FORWARD_PORT,
            REMOTE_HOST,
            REMOTE_PORT,
            transport,
            LOCAL_FORWARD_HOST,
            stop_event=stop_event,
            ready_event=ready_event,
            error_holder=error_holder,
        )

    thread = threading.Thread(target=_forward, daemon=True)
    thread.start()
    ready_event.wait(timeout=5)
    if error_holder.get("error"):
        raise RuntimeError(f"Failed to start local forward server: {error_holder['error']}")
    if not ready_event.is_set():
        raise TimeoutError("Timed out waiting for local forward server to start.")

    print(
        "SSH tunnel ready (paramiko): "
        f"{LOCAL_FORWARD_HOST}:{LOCAL_FORWARD_PORT} -> {REMOTE_HOST}:{REMOTE_PORT}"
    )

    def close_tunnel():
        stop_event.set()
        thread.join(timeout=2)
        client.close()

    return close_tunnel


def forward_tunnel(
    local_port,
    remote_host,
    remote_port,
    transport,
    local_host="127.0.0.1",
    stop_event=None,
    ready_event=None,
    error_holder=None,
):
    """精简版 local port forwarding，替代 paramiko.forward (Paramiko 4 已移除)."""
    import socketserver
    import select

    class _ForwardServer(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

        def __init__(self, server_address, handler_cls, transport_obj, chan_host, chan_port):
            super().__init__(server_address, handler_cls)
            self.transport = transport_obj
            self.chan_host = chan_host
            self.chan_port = chan_port

    class _Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                chan = self.server.transport.open_channel(
                    "direct-tcpip",
                    (self.server.chan_host, self.server.chan_port),
                    self.request.getpeername(),
                )
            except Exception:
                return
            if chan is None:
                return

            while True:
                r, _, _ = select.select([self.request, chan], [], [], 1)
                if self.request in r:
                    data = self.request.recv(1024)
                    if not data:
                        break
                    chan.send(data)
                if chan in r:
                    data = chan.recv(1024)
                    if not data:
                        break
                    self.request.send(data)

            chan.close()
            self.request.close()

    try:
        server = _ForwardServer(
            (local_host, local_port),
            _Handler,
            transport,
            remote_host,
            remote_port,
        )
        server.timeout = 0.5
        if ready_event:
            ready_event.set()

        while True:
            if stop_event and stop_event.is_set():
                break
            server.handle_request()
    except Exception as exc:
        if error_holder is not None:
            error_holder["error"] = exc
        if ready_event and not ready_event.is_set():
            ready_event.set()
    finally:
        if "server" in locals():
            server.server_close()


if __name__ == "__main__":
    if FORWARD_MODE == "asyncssh":
        stop_tunnel = start_asyncssh_tunnel_sync()
        try:
            if TUNNEL_READY_DELAY_SEC:
                time.sleep(TUNNEL_READY_DELAY_SEC)
            run_client(LOCAL_FORWARD_HOST, LOCAL_FORWARD_PORT)
        finally:
            stop_tunnel()
    elif FORWARD_MODE == "paramiko":
        stop_tunnel = start_paramiko_tunnel_sync()
        try:
            if TUNNEL_READY_DELAY_SEC:
                time.sleep(TUNNEL_READY_DELAY_SEC)
            run_client(LOCAL_FORWARD_HOST, LOCAL_FORWARD_PORT)
        finally:
            stop_tunnel()
    else:
        run_client("127.0.0.1", 9000)
