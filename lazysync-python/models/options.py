"""
选项数据模型模块
定义rsync选项的数据结构
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import json
from pathlib import Path
from config.constants import OPTIONS_JSON_PATH


@dataclass
class RsyncOption:
    """
    Rsync选项数据模型
    
    表示一个rsync命令行选项，包含短选项、长选项、是否需要值以及描述信息。
    """
    short_option: Optional[str]
    """短选项，如 '-a', '-v' 等"""
    
    long_option: Optional[str]
    """长选项，如 '--archive', '--verbose' 等"""
    
    needs_value: bool
    """是否需要值，如 '--port=22' 或 '--port 22'"""
    
    description: str
    """选项的描述说明"""
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RsyncOption':
        """
        从字典创建RsyncOption实例
        
        Args:
            data: 包含选项数据的字典
            
        Returns:
            RsyncOption实例
        """
        return cls(
            short_option=data.get('short_option'),
            long_option=data.get('long_option'),
            needs_value=data.get('needs_value', False),
            description=data.get('description', '')
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将RsyncOption转换为字典
        
        Returns:
            包含选项数据的字典
        """
        return {
            'short_option': self.short_option,
            'long_option': self.long_option,
            'needs_value': self.needs_value,
            'description': self.description
        }


class OptionsLoader:
    """
    Rsync选项加载器
    
    负责从JSON文件加载rsync选项数据，并提供查询接口。
    """
    
    def __init__(self, options_file: Path = OPTIONS_JSON_PATH):
        """
        初始化选项加载器
        
        Args:
            options_file: 选项JSON文件路径
        """
        self.options_file = options_file
        self._options: List[RsyncOption] = []
        self._load_options()
    
    def _load_options(self) -> None:
        """从JSON文件加载选项数据"""
        try:
            with open(self.options_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._options = [RsyncOption.from_dict(item) for item in data]
        except FileNotFoundError:
            self._options = []
        except json.JSONDecodeError:
            self._options = []
    
    def get_all_options(self) -> List[RsyncOption]:
        """
        获取所有选项
        
        Returns:
            所有RsyncOption实例的列表
        """
        return self._options.copy()
    
    def get_short_options(self) -> List[RsyncOption]:
        """
        获取所有有短选项的选项
        
        Returns:
            包含短选项的RsyncOption实例列表
        """
        return [opt for opt in self._options if opt.short_option and not opt.needs_value]
    
    def get_long_only_options(self) -> List[RsyncOption]:
        """
        获取只有长选项（没有短选项）的选项
        
        Returns:
            只有长选项的RsyncOption实例列表
        """
        return [opt for opt in self._options 
                if opt.long_option and not opt.short_option and not opt.needs_value]
    
    def get_value_options(self) -> List[RsyncOption]:
        """
        获取需要值的选项
        
        Returns:
            需要值的RsyncOption实例列表
        """
        return [opt for opt in self._options if opt.needs_value]
