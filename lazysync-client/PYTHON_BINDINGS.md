# Python 绑定使用说明

这个项目现在支持通过 PyO3 直接调用 Rust 函数，无需通过 HTTP API。

## 安装依赖

首先需要安装 `maturin`，这是构建 PyO3 扩展的工具：

```bash
pip install maturin
```

或者使用 cargo：

```bash
cargo install maturin
```

## 构建 Python 扩展

在 `lazysync-client` 目录下运行：

```bash
maturin develop
```

或者构建 wheel 文件：

```bash
maturin build
```

### Python 3.13 兼容性

如果使用 Python 3.13，项目已配置使用 ABI3 模式（`abi3-py37` feature），这允许与 Python 3.7+ 兼容，包括 Python 3.13。

如果仍然遇到版本兼容性问题，可以设置环境变量：

```bash
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
maturin develop
```

## 使用方法

### 基本用法

```python
import rfb_client

# 1. 创建client对象并连接到远程server
client = rfb_client.PyClient("127.0.0.1:9000")

# 2. 调用client的函数得到指定路径下的文件信息
entries = client.get_path("/path/to/directory")

# entries 是一个字典列表，每个字典包含：
# - name: 文件名
# - is_dir: 是否为目录
# - size: 文件大小（字节）
# - permissions: 权限字符串
# - modified: 修改时间

for entry in entries:
    print(f"{entry['name']} - {'DIR' if entry['is_dir'] else 'FILE'}")
```

### API 说明

#### `PyClient(server_addr: str)`

创建客户端并连接到服务器。

- `server_addr`: 服务器地址，格式为 "host:port"，例如 "127.0.0.1:9000"

#### `get_path(path: str) -> List[Dict]`

获取指定路径下的文件和目录列表。会自动检查缓存，如果有缓存则立即返回，否则请求服务器并等待响应。

- `path`: 要查询的路径
- 返回: 文件/目录条目列表，每个条目是一个字典

#### `request_path(path: str) -> None`

异步请求路径数据（不等待结果）。主要用于预加载数据。

- `path`: 要请求的路径

## 示例

查看 `example_python_direct.py` 获取完整示例。

## 与 HTTP API 方式的对比

### HTTP API 方式（旧方式）
```python
import requests
response = requests.post("http://127.0.0.1:8080/get", json={"path": "/path"})
data = response.json()
```

### 直接调用方式（新方式）
```python
import rfb_client
client = rfb_client.PyClient("127.0.0.1:9000")
entries = client.get_path("/path")
```

新方式的优势：
- 更简单，无需 HTTP 服务器
- 更高效，直接调用 Rust 函数
- 更少的依赖（不需要 requests 库）
- 类型安全（通过 PyO3）

