import asyncio
import pexpect
import threading
import queue


class AsyncPexpect:
    """将 pexpect 包装为异步接口"""
    
    def __init__(self, command, encoding="utf-8"):
        """
        初始化异步 pexpect
        
        Args:
            command: 要执行的命令
            encoding: 编码格式
        """
        self.child = pexpect.spawn(command, encoding=encoding)
        self.output_queue = queue.Queue()
        self.running = True
        self.read_thread = None
        
    def _read_output(self):
        """在后台线程中读取输出"""
        while self.running:
            try:
                # 使用非阻塞方式读取
                index = self.child.expect([pexpect.TIMEOUT, pexpect.EOF], timeout=0.1)
                if self.child.before:
                    # 将输出放入队列
                    self.output_queue.put(("output", self.child.before))
                if index == 1:  # EOF
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
        self.child.sendline(line)
    
    def send(self, data):
        """发送数据"""
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
    
    def close(self):
        """关闭进程"""
        self.running = False
        if self.child and self.child.isalive():
            self.child.close()


async def ssh_output(async_child):
    """异步读取 ssh 输出并打印"""
    while True:
        event_type, data = await async_child.read_output()
        if event_type == "output":
            print(data, end="", flush=True)
        elif event_type == "eof":
            print("\n[SSH 连接已关闭]")
            break
        await asyncio.sleep(0.01)  # 避免 CPU 占用过高


async def ssh_input(async_child):
    """异步接受用户输入并发送到 ssh"""
    loop = asyncio.get_event_loop()
    while True:
        try:
            # 异步读取用户输入
            user_input = await loop.run_in_executor(None, input, "> ")
            if user_input.strip():
                async_child.sendline(user_input)
        except (EOFError, KeyboardInterrupt):
            print("\n[退出]")
            async_child.close()
            break


async def main():
    # 创建异步 pexpect 实例
    async_child = AsyncPexpect("ssh polixir@172.16.0.105", encoding="utf-8")
    
    try:
        # 并行运行输出和输入协程
        await asyncio.gather(
            ssh_output(async_child),
            ssh_input(async_child)
        )
    finally:
        async_child.close()


if __name__ == "__main__":
    asyncio.run(main())

