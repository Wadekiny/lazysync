#!/usr/bin/env python3
"""
测试 SSHFileManager 的脚本（同步版本，方便打断点）
不使用 TUI，直接测试文件管理器功能
"""

import asyncio
import sys
from pathlib import Path

# 添加项目路径到 sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from backend.file_manager import SSHFileManager
from backend.ssh_client import InteractiveSSHClient, PasswordCancelledError
from utils.logger import log


def run_async(coro):
    """
    同步运行异步函数的辅助函数
    方便在同步代码中打断点调试
    
    Args:
        coro: 协程对象
        
    Returns:
        协程的返回值
    """
    try:
        # 尝试获取当前运行的事件循环
        asyncio.get_running_loop()
        # 如果已经在事件循环中运行，抛出错误提示
        raise RuntimeError(
            "Cannot run async function synchronously when already in an event loop. "
            "This function should only be called from synchronous code."
        )
    except RuntimeError:
        # 没有运行的事件循环，可以使用 asyncio.run()
        # 这样可以方便在同步代码中打断点调试
        return asyncio.run(coro)


async def password_prompt_callback(prompt: str, mask_input: bool) -> str:
    """
    密码提示回调函数
    
    Args:
        prompt: 提示文本
        mask_input: 是否隐藏输入（True=密码，False=普通文本）
        
    Returns:
        用户输入的字符串
    """
    if mask_input:
        import getpass
        return getpass.getpass(prompt)
    else:
        return input(prompt)


def test_ssh_file_manager():
    """测试 SSHFileManager 的功能"""
    
    # SSH 连接参数（请根据实际情况修改）
    print("=== SSH File Manager Test ===\n")
    
    # 从命令行参数或环境变量获取 SSH 信息
    import os
    host = os.getenv("SSH_HOST", "116.172.93.164")
    port = int(os.getenv("SSH_PORT", "29293"))
    username = os.getenv("SSH_USER", "ubuntu")
    
    # 或者从命令行参数获取
    if len(sys.argv) >= 4:
        host = sys.argv[1]
        port = int(sys.argv[2])
        username = sys.argv[3]
    else:
        host = "116.172.93.164"
        port = 29293
        username = "ubuntu"
        print("Usage: python test_ssh_file_manager.py <host> <port> <username>")
        print("Or set environment variables: SSH_HOST, SSH_PORT, SSH_USER")
        print("\nExample:")
        print("  python test_ssh_file_manager.py 192.168.1.100 22 ubuntu")
        print("  SSH_HOST=192.168.1.100 SSH_PORT=22 SSH_USER=ubuntu python test_ssh_file_manager.py")
        # return
    
    print(f"Connecting to {username}@{host}:{port}...")
    
    # 创建 SSHFileManager 实例
    fm = SSHFileManager()
    
    try:
        # 1. 连接到 SSH 服务器
        print("\n[1] Connecting to SSH server...")
        connect_kwargs = {
            "host": host,
            "port": port,
            "username": username,
            "client_factory": lambda: InteractiveSSHClient(
                password_prompt_callback=password_prompt_callback
            ),
            "known_hosts": None,
        }
        
        run_async(fm.connect(**connect_kwargs))
        print(f"✓ Connected successfully!")
        print(f"  Current path: {fm.current_path}")
        
        # 2. 获取当前目录内容
        print("\n[2] Getting current directory contents...")
        print(f"  Current path: {fm.current_path}")
        print(f"  Client status: {'Connected' if fm.client else 'Not connected'}")
        print(f"  Local port: {fm.local_port}")
        try:
            contents = fm.get_contents(show_hidden=False)
            print(f"✓ Found {len(contents)} items:")
        except Exception as e:
            print(f"✗ Error getting contents: {e}")
            import traceback
            traceback.print_exc()
            return
        for i, (name, path) in enumerate(contents[:10], 1):  # 只显示前10个
            print(f"  {i}. {name} -> {path}")
        if len(contents) > 10:
            print(f"  ... and {len(contents) - 10} more items")
        
        # 3. 测试切换目录（如果有目录的话）
        print("\n[3] Testing directory navigation...")
        dirs = [(name, path) for name, path in contents if name.endswith("/") and name != "../"]
        if dirs:
            test_dir_name, test_dir_path = dirs[0]
            print(f"  Trying to enter: {test_dir_name}")
            if run_async(fm.change_dir(test_dir_path)):
                print(f"✓ Successfully changed to: {fm.current_path}")
                
                # 获取新目录的内容
                new_contents = run_async(fm.get_contents(show_hidden=False))
                print(f"  Found {len(new_contents)} items in new directory")
            else:
                print(f"✗ Failed to change directory")
        else:
            print("  No directories found to test")
        
        # 4. 测试返回父目录
        print("\n[4] Testing parent directory navigation...")
        if run_async(fm.change_parent()):
            print(f"✓ Successfully changed to parent: {fm.current_path}")
        else:
            print("✗ Failed to change to parent (might be at root)")
        
        # 5. 测试显示隐藏文件
        print("\n[5] Testing hidden files...")
        contents_with_hidden = run_async(fm.get_contents(show_hidden=True))
        hidden_count = len(contents_with_hidden) - len(contents)
        print(f"✓ Found {hidden_count} hidden items")
        
        # 6. 测试获取特定路径
        print("\n[6] Testing getting specific path...")
        home_path = fm.current_path
        home_contents = run_async(fm.get_contents(show_hidden=False))
        print(f"✓ Got {len(home_contents)} items from {home_path}")
        
        print("\n=== All tests completed successfully! ===")
        
    except PasswordCancelledError:
        print("\n✗ Password input was cancelled")
    except Exception as e:
        print(f"\n✗ Error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理资源
        print("\n[Cleanup] Closing connections...")
        try:
            # 检查是否有连接需要关闭
            if fm.conn is not None:
                # 使用新的 asyncio.run() 来运行 cleanup
                # 因为之前的事件循环可能已经关闭
                try:
                    asyncio.run(fm.close())
                    print("✓ Connections closed")
                except RuntimeError:
                    # 如果事件循环已经在运行，尝试其他方法
                    print("⚠ Event loop already closed, skipping cleanup")
        except Exception as e:
            print(f"✗ Error closing connections: {e}")


if __name__ == "__main__":
    # 运行测试（同步版本，可以直接打断点）
    test_ssh_file_manager()

