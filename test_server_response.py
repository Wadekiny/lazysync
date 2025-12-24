#!/usr/bin/env python3
"""
测试脚本：检查服务器发送的响应格式
"""
import socket
import json

# 连接到服务器
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('127.0.0.1', 9000))

# 发送请求
request = {
    "id": 1,
    "path": "/tmp"
}
request_json = json.dumps(request) + "\n"
sock.sendall(request_json.encode())

# 接收响应
response = sock.recv(4096).decode()
print("Server response:")
print(response)
print("\nParsed JSON:")
try:
    resp_obj = json.loads(response.strip())
    print(json.dumps(resp_obj, indent=2))
    print("\nResponse keys:", list(resp_obj.keys()))
except Exception as e:
    print(f"Error parsing JSON: {e}")

sock.close()

