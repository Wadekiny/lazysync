"""
Rsync命令构建器模块
负责根据用户选择的选项和路径构建rsync命令字符串
"""

from typing import List, Optional


class RsyncCommandBuilder:
    """
    Rsync命令构建器
    
    根据源路径、目标路径和选中的选项构建完整的rsync命令。
    """
    
    @staticmethod
    def build_command(
        source_path: str,
        target_path: str,
        short_options: Optional[List[str]] = None,
        long_options: Optional[List[str]] = None,
        value_options: Optional[List[str]] = None
    ) -> str:
        """
        构建rsync命令字符串
        
        Args:
            source_path: 源路径
            target_path: 目标路径
            short_options: 选中的短选项列表（如 ['-a', '-v']）
            long_options: 选中的长选项列表（如 ['--verbose']）
            value_options: 选中的带值选项列表（如 ['--port=22', '--exclude=*.log']）
            
        Returns:
            完整的rsync命令字符串
        """
        # 收集所有选项
        all_options = []
        
        # 处理短选项：合并为单个参数（如 -a -v -z 变成 -avz）
        if short_options:
            short_letters = []
            for opt in short_options:
                if opt.startswith('-') and len(opt) == 2:
                    short_letters.append(opt[1])
            
            if short_letters:
                all_options.append('-' + ''.join(short_letters))
        
        # 添加长选项
        if long_options:
            all_options.extend(long_options)
        
        # 添加带值的选项
        if value_options:
            all_options.extend(value_options)
        
        # 构建命令
        options_str = " ".join(all_options) if all_options else ""
        
        if options_str:
            cmd = f"rsync {options_str} {source_path} {target_path}"
        else:
            cmd = f"rsync {source_path} {target_path}"
        
        # 清理多余的空格
        cmd = " ".join(cmd.split())
        
        return cmd
    
    @staticmethod
    def build_from_selected_options(
        source_path: str,
        target_path: str,
        selected_short: List[str],
        selected_long: List[str],
        selected_value: List[str]
    ) -> str:
        """
        从选中的选项构建命令（便捷方法）
        
        Args:
            source_path: 源路径
            target_path: 目标路径
            selected_short: 从短选项面板获取的选中选项
            selected_long: 从长选项面板获取的选中选项
            selected_value: 从值选项面板获取的选中选项
            
        Returns:
            完整的rsync命令字符串
        """
        return RsyncCommandBuilder.build_command(
            source_path=source_path,
            target_path=target_path,
            short_options=selected_short,
            long_options=selected_long,
            value_options=selected_value
        )
