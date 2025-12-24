#!/usr/bin/env python3
"""
Python客户端示例，用于调用Rust HTTP接口获取路径数据
"""

import json
import requests
from typing import Dict, List, Any, Optional


def request_path(path: str) -> Dict[str, Any]:
    """
    向Rust客户端发送路径请求（异步，不等待结果）
    
    Args:
        path: 要请求的路径
        
    Returns:
        包含success和message的响应字典
    """
    url = "http://127.0.0.1:8080/request"
    payload = {"path": path}
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"success": False, "message": f"Request failed: {str(e)}"}


def get_path(path: str) -> Optional[Dict[str, Any]]:
    """
    获取指定路径的数据（带cache检查）
    
    这个函数会：
    1. 先检查cache，如果有则立即返回
    2. 如果没有cache，则请求server并等待响应
    
    Args:
        path: 要查询的路径
        
    Returns:
        包含success, path, entries, from_cache的响应字典，失败返回None
    """
    url = "http://127.0.0.1:8080/get"
    payload = {"path": path}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error getting path {path}: {str(e)}")
        return None


def get_path_entries(path: str) -> List[Dict[str, Any]]:
    """
    获取指定路径的条目列表（使用新的/get API）
    
    Args:
        path: 要查询的路径
        
    Returns:
        该路径下的文件和目录列表
    """
    result = get_path(path)
    if result and result.get("success"):
        return result.get("entries", [])
    return []


def get_path_dirs(path: str) -> List[Dict[str, Any]]:
    """
    获取指定路径下的目录列表（只返回目录，不包含文件）
    
    Args:
        path: 要查询的路径
        
    Returns:
        该路径下的目录列表
    """
    entries = get_path_entries(path)
    return [entry for entry in entries if entry.get("is_dir", False)]


def read_cache() -> Dict[str, List[Dict[str, Any]]]:
    """
    读取cache.json文件（已废弃，建议使用get_path API）
    
    Returns:
        字典格式：{"path": [files or dirs in path]}
    """
    try:
        with open("cache.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        print(f"Error parsing cache.json: {e}")
        return {}


def format_size(size: int) -> str:
    """
    格式化文件大小
    
    Args:
        size: 文件大小（字节）
        
    Returns:
        格式化后的大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def print_entry_info(entry: Dict[str, Any]) -> None:
    """
    打印单个文件/目录的详细信息
    
    Args:
        entry: 文件/目录条目字典
    """
    name = entry.get('name', '')
    is_dir = entry.get('is_dir', False)
    size = entry.get('size', 0)
    permissions = entry.get('permissions', '')
    modified = entry.get('modified', '')
    
    # 格式化显示
    type_marker = 'd' if is_dir else '-'
    size_str = format_size(size) if not is_dir else '-'
    
    print(f"  {permissions:10} {modified:19} {size_str:>10} {name}")


if __name__ == "__main__":
    # 示例1: 使用新的/get API获取路径数据（带cache检查）
    path_request = "/Users/wadekiny/Workspace/test/rsync.txt"
    print(f"Getting path data for: {path_request}")
    result = get_path(path_request)
    
    if result:
        print(f"Success: {result.get('success')}")
        print(f"From cache: {result.get('from_cache')}")
        print(f"Entries count: {len(result.get('entries', []))}")
        print()
        
        # 显示所有文件和目录的详细信息
        entries = result.get('entries', [])
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
        result2 = get_path(path_request)
        if result2:
            print(f"From cache: {result2.get('from_cache')}")
    else:
        print("Failed to get path data")

