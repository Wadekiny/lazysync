#!/usr/bin/env python3
"""
Use asyncssh to create a local port forward and stay running (like `ssh -N -L ...`).
"""

import asyncio
import getpass
import os
import socket
import signal
import sys
import time
from multiprocessing import Process

import rfb_client

try:
    import asyncssh
except ImportError:
    print("Error: asyncssh module not found.")
    print("Please install it first:")
    print("  pip install asyncssh")
    sys.exit(1)

# SSH server info
SSH_HOST = "116.172.93.227"
SSH_PORT = 29293
SSH_USER = "ubuntu"

# Optional auth
SSH_PASSWORD = None  # can also set LAZYSYNC_SSH_PASSWORD
SSH_KEY_PATH = None  # can also set LAZYSYNC_SSH_KEY_PATH

# Port forwarding config (local -> remote)
LOCAL_FORWARD_HOST = "127.0.0.1"
LOCAL_FORWARD_PORT = 9000
REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = 9000


def _build_connect_kwargs(overrides=None, allow_prompt=True):
    overrides = overrides or {}
    connect_kwargs = {
        "host": SSH_HOST,
        "port": SSH_PORT,
        "username": SSH_USER,
    }
    env_password = os.getenv("LAZYSYNC_SSH_PASSWORD")
    env_key_path = os.getenv("LAZYSYNC_SSH_KEY_PATH")

    if overrides.get("password"):
        connect_kwargs["password"] = overrides["password"]
    elif env_password:
        connect_kwargs["password"] = env_password
    elif SSH_PASSWORD:
        connect_kwargs["password"] = SSH_PASSWORD

    if overrides.get("key_path"):
        connect_kwargs["client_keys"] = [overrides["key_path"]]
    elif env_key_path:
        connect_kwargs["client_keys"] = [env_key_path]
    elif SSH_KEY_PATH:
        connect_kwargs["client_keys"] = [SSH_KEY_PATH]

    if "password" not in connect_kwargs and "client_keys" not in connect_kwargs:
        if allow_prompt and sys.stdin.isatty():
            typed = getpass.getpass(
                "未设置SSH_PASSWORD或SSH_KEY_PATH，如需密码登录请输入（留空则使用默认密钥/agent）: "
            )
            if typed:
                connect_kwargs["password"] = typed
        else:
            print("未设置SSH_PASSWORD或SSH_KEY_PATH，且当前无交互输入；将尝试默认密钥/agent。")

    return connect_kwargs


def _collect_auth_overrides():
    overrides = {}
    if os.getenv("LAZYSYNC_SSH_PASSWORD") or SSH_PASSWORD:
        return overrides
    if os.getenv("LAZYSYNC_SSH_KEY_PATH") or SSH_KEY_PATH:
        return overrides
    if sys.stdin.isatty():
        typed = getpass.getpass(
            "未设置SSH_PASSWORD或SSH_KEY_PATH，如需密码登录请输入（留空则使用默认密钥/agent）: "
        )
        if typed:
            overrides["password"] = typed
    else:
        print("未设置SSH_PASSWORD或SSH_KEY_PATH，且当前无交互输入；将尝试默认密钥/agent。")
    return overrides


async def _run_tunnel(overrides):
    connect_kwargs = _build_connect_kwargs(overrides=overrides, allow_prompt=False)
    async with asyncssh.connect(**connect_kwargs) as conn:
        listener = await conn.forward_local_port(
            LOCAL_FORWARD_HOST,
            LOCAL_FORWARD_PORT,
            REMOTE_HOST,
            REMOTE_PORT,
        )
        print(
            "SSH tunnel ready (asyncssh): "
            f"{LOCAL_FORWARD_HOST}:{LOCAL_FORWARD_PORT} -> {REMOTE_HOST}:{REMOTE_PORT}"
        )

        stop_event = asyncio.Event()

        def _stop(*_args):
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _stop)

        await stop_event.wait()
        listener.close()
        await listener.wait_closed()


def _tunnel_process_main(overrides):
    asyncio.run(_run_tunnel(overrides))


def _wait_for_local_port(host, port, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


if __name__ == "__main__":
    # overrides = _collect_auth_overrides()
    # tunnel_proc = Process(target=_tunnel_process_main, args=(overrides,))
    # tunnel_proc.daemon = True
    # tunnel_proc.start()

    # if not _wait_for_local_port(LOCAL_FORWARD_HOST, LOCAL_FORWARD_PORT, timeout_s=10.0):
    #     print("本地端口转发未就绪，请检查SSH连接与端口配置。")
    #     tunnel_proc.terminate()
    #     sys.exit(1)

    host = "127.0.0.1"
    port = 9000
    client = rfb_client.PyClient(f"{host}:{port}", is_hash=True)
    print(client.get_path("/Users/wadekiny/Workspace"))
    print("f")
