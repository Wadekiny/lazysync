"""
选项面板组件模块
包含rsync选项的UI组件（短选项、长选项、值选项）
"""

from typing import List, Dict, Any, Optional
from textual.widgets import ListView, ListItem, Checkbox, Input, Label
from textual.binding import Binding
from textual.containers import Horizontal

from models.messages import OptionSelected
from models.options import OptionsLoader, RsyncOption
from frontend.widgets.base.list_view_ui import ListViewUI


class FancyCheckbox(Checkbox):
    """
    自定义复选框组件
    
    使用自定义符号显示选中/未选中状态。
    """
    checked_symbol = "[✔︎]"
    unchecked_symbol = "[ ]"
    
    def render(self):
        """
        复写渲染逻辑：把前缀替换为符号
        
        Returns:
            渲染后的文本
        """
        symbol = self.checked_symbol if self.value else self.unchecked_symbol
        return f"{symbol} {self.label}"


class OptionsPanel(ListViewUI):
    """
    选项面板基础类
    
    支持显示短参数或长参数，不包含需要值的选项。
    """
    
    BINDINGS = ListViewUI.BINDINGS.copy()
    BINDINGS += [
        Binding("space", "toggle_selected", "Toggle", show=True),
    ]
    
    def __init__(self, show_short: bool = True, **kwargs):
        """
        初始化选项面板
        
        Args:
            show_short: True显示短参数，False显示长参数
            **kwargs: 传递给父类的其他参数
        """
        # 加载选项数据
        loader = OptionsLoader()
        self.options = loader.get_short_options() if show_short else loader.get_long_only_options()
        
        self.show_short = show_short
        
        # 存储选项信息，key是ListItem的索引，value是选项数据
        self.option_data: Dict[int, RsyncOption] = {}
        
        items = []
        index = 0
        for opt in self.options:
            if show_short:
                # 只显示有短参数的选项
                if opt.short_option:
                    label = f"{opt.short_option} ({opt.long_option})" if opt.long_option else opt.short_option
                    checkbox = FancyCheckbox(label)
                    item = ListItem(checkbox)
                    items.append(item)
                    self.option_data[index] = opt
                    index += 1
            else:
                # 只显示有长参数但没有短参数的选项
                if opt.long_option and not opt.short_option:
                    label = opt.long_option
                    checkbox = FancyCheckbox(label)
                    item = ListItem(checkbox)
                    items.append(item)
                    self.option_data[index] = opt
                    index += 1
        
        # 如果没有指定id，使用默认id
        if 'id' not in kwargs:
            kwargs['id'] = "short_options" if show_short else "long_options"
        super().__init__(*items, **kwargs)
    
    def on_mount(self) -> None:
        """挂载时，设置默认在第一行并显示其description"""
        if len(self.children) > 0:
            self.index = 0
        if self.index is not None and self.index in self.option_data:
            opt = self.option_data[self.index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
    
    def action_toggle_selected(self) -> None:
        """按space键切换当前选中项的checkbox状态"""
        index = self.index
        if index is not None and index < len(self.children):
            item = self.children[index]
            if isinstance(item, ListItem):
                checkbox = item.children[0] if item.children else None
                if isinstance(checkbox, FancyCheckbox):
                    # 直接设置值，Checkbox会自动触发Changed事件
                    checkbox.value = not checkbox.value
                    # 确保触发Changed事件以更新preview
                    from textual.widgets import Checkbox
                    checkbox.post_message(Checkbox.Changed(checkbox, checkbox.value))
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """当选中项变化时，发送消息更新description"""
        index = self.index
        if index is not None and index in self.option_data:
            opt = self.option_data[index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
    
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """当高亮项变化时（使用j/k导航），也更新description"""
        index = self.index
        if index is not None and index in self.option_data:
            opt = self.option_data[index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
    
    def on_focus(self, event) -> None:
        """当窗口获得焦点时，更新description"""
        index = self.index
        if index is not None and index in self.option_data:
            opt = self.option_data[index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
    
    def get_selected_options(self) -> List[str]:
        """
        获取所有选中的选项，返回选项字符串列表
        
        Returns:
            选中的选项列表，短选项保持独立（如 ['-a', '-v', '-z']）
            合并逻辑由命令构建器处理
        """
        result = []
        
        for index, item in enumerate(self.children):
            if isinstance(item, ListItem):
                checkbox = item.children[0] if item.children else None
                if isinstance(checkbox, FancyCheckbox) and checkbox.value:
                    if index in self.option_data:
                        opt = self.option_data[index]
                        # 优先使用短参数，如果没有则使用长参数
                        if opt.short_option:
                            result.append(opt.short_option)
                        elif opt.long_option:
                            result.append(opt.long_option)
        
        return result
    
    def action_go_first(self):
        """gg: 跳转到第一行"""
        if len(self.children) > 0:
            self.index = 0
    
    def action_go_last(self):
        """G: 跳转到最后一行"""
        if len(self.children) > 0:
            self.index = len(self.children) - 1


class ValueOptionItem(ListItem):
    """
    需要值的选项项组件
    
    包含checkbox和值显示，支持编辑值。
    """
    
    def __init__(self, option_data: RsyncOption, value: str = "", **kwargs):
        """
        初始化值选项项
        
        Args:
            option_data: 选项数据
            value: 初始值
            **kwargs: 传递给父类的其他参数
        """
        self.option_data = option_data
        self.value = value
        self.is_editing = False
        
        # 创建显示内容
        opt_name = option_data.long_option or option_data.short_option or ''
        checkbox = FancyCheckbox(opt_name)
        self.checkbox = checkbox
        
        # 创建值显示标签
        value_label = Label(f" = {value}" if value else " = (no value)", id="value_label")
        self.value_label = value_label
        
        # 创建输入框（初始隐藏）
        value_input = Input(value=value, placeholder="Enter value...", id="value_input")
        value_input.display = False
        self.value_input = value_input
        
        # 使用Horizontal容器来并排显示
        container = Horizontal(checkbox, value_label, value_input, id="value_option_container")
        super().__init__(container, **kwargs)
    
    def start_editing(self):
        """开始编辑值"""
        self.is_editing = True
        self.value_label.display = False
        self.value_input.display = True
        self.value_input.focus()
    
    def stop_editing(self):
        """停止编辑值"""
        self.is_editing = False
        self.value = self.value_input.value
        self.value_label.update(f" = {self.value}" if self.value else " = (no value)")
        self.value_label.display = True
        self.value_input.display = False


class ValueOptionsPanel(ListView):
    """
    需要输入值的选项面板组件
    """
    
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=True),
        Binding("k", "cursor_up", "Up", show=True),
        Binding("space", "toggle_selected", "Toggle", show=True),
        Binding("enter", "edit_value", "Edit Value", show=True),
        Binding("escape", "cancel_edit", "Cancel Edit", show=True),
        Binding("g,g", "go_first", "First", show=False),
        Binding("G", "go_last", "Last", show=False),
    ]
    
    def __init__(self, **kwargs):
        """
        初始化值选项面板
        
        Args:
            **kwargs: 传递给父类的其他参数
        """
        # 加载选项数据
        loader = OptionsLoader()
        self.options = loader.get_value_options()
        
        # 存储选项信息，key是ListItem的索引，value是选项数据
        self.option_data: Dict[int, RsyncOption] = {}
        # 存储每个选项的值，key是选项的long_option或short_option
        self.option_values: Dict[str, str] = {}
        # 当前正在编辑的索引和输入框
        self.editing_index: Optional[int] = None
        self.editing_input: Optional[Input] = None
        
        items = []
        index = 0
        for opt in self.options:
            # 获取选项名称
            opt_name = opt.long_option or opt.short_option or ''
            # 获取已存储的值（如果有）
            value = self.option_values.get(opt_name, "")
            
            item = ValueOptionItem(opt, value=value)
            items.append(item)
            self.option_data[index] = opt
            index += 1
        
        if 'id' not in kwargs:
            kwargs['id'] = "value_options"
        super().__init__(*items, **kwargs)
    
    def get_selected_options(self) -> List[str]:
        """
        获取所有选中的选项（带值），返回选项字符串列表
        
        Returns:
            选中的选项列表，格式如 ['--port=22', '--exclude=*.log']
        """
        selected = []
        # 只处理ValueOptionItem，忽略其他类型的children（如输入框）
        list_items = [child for child in self.children if isinstance(child, ValueOptionItem)]
        
        for index, item in enumerate(list_items):
            if item.checkbox.value:  # 如果checkbox被选中
                opt = self.option_data[index]
                opt_name = opt.long_option or opt.short_option or ''
                # 从存储的值中获取，如果没有则从item.value获取
                value = self.option_values.get(opt_name, item.value if hasattr(item, 'value') else "")
                
                # 构建选项字符串
                if opt.short_option:
                    option_str = opt.short_option
                else:
                    option_str = opt.long_option or ''
                
                # 如果有值，添加到选项中
                if value:
                    # 检查选项是否需要=号（从原始数据判断）
                    # 如果长选项名包含=，说明应该用=连接
                    long_opt = opt.long_option or ''
                    if '=' in long_opt:
                        # 提取选项名（去掉=后面的部分）
                        option_base = long_opt.split('=')[0] if '=' in long_opt else long_opt
                        selected.append(f"{option_base}={value}")
                    else:
                        # 否则用空格分隔
                        selected.append(f"{option_str} {value}")
                else:
                    # 没有值时不添加该选项（需要值的选项必须有值）
                    pass
        return selected
    
    def on_mount(self) -> None:
        """挂载时，设置默认在第一行并显示其description"""
        if len(self.children) > 0:
            self.index = 0
        if self.index is not None and self.index in self.option_data:
            opt = self.option_data[self.index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
    
    def action_go_first(self):
        """gg: 跳转到第一行"""
        if len(self.children) > 0:
            self.index = 0
    
    def action_go_last(self):
        """G: 跳转到最后一行"""
        if len(self.children) > 0:
            self.index = len(self.children) - 1
    
    def action_toggle_selected(self) -> None:
        """按space键切换当前选中项的checkbox状态"""
        # 检查是否有正在编辑的项
        for item in self.children:
            if isinstance(item, ValueOptionItem) and item.is_editing:
                return  # 正在编辑时不允许切换
        index = self.index
        if index is not None and index < len(self.children):
            item = self.children[index]
            if isinstance(item, ValueOptionItem):
                # 切换checkbox值，这会自动触发Changed事件
                item.checkbox.value = not item.checkbox.value
                # 确保触发Changed事件以更新preview
                from textual.widgets import Checkbox
                item.checkbox.post_message(Checkbox.Changed(item.checkbox, item.checkbox.value))
    
    def action_edit_value(self) -> None:
        """按enter键开始编辑当前选中项的值"""
        # 如果输入框正在编辑，不处理（让输入框自己处理enter键）
        if self.editing_input is not None and self.editing_input.has_focus:
            return
        
        if self.editing_index is not None:
            return  # 已经在编辑中
        
        index = self.index
        if index is None:
            return
        
        # 获取实际的ValueOptionItem列表（排除输入框等）
        list_items = [child for child in self.children if isinstance(child, ValueOptionItem)]
        
        if index < len(list_items):
            item = list_items[index]
            # 获取当前值
            opt = self.option_data[index]
            opt_name = opt.long_option or opt.short_option or ''
            current_value = self.option_values.get(opt_name, item.value if hasattr(item, 'value') else "")
            
            # 隐藏ValueOptionsPanel的内容（隐藏所有子项）
            for child in self.children:
                if isinstance(child, ValueOptionItem):
                    child.display = False
            
            # 创建输入框
            value_input = Input(value=current_value, placeholder="Enter value...", id="value_edit_input")
            value_input.border_title = "Enter Value (Press Enter to confirm, Esc to cancel)"
            self.editing_input = value_input
            self.editing_index = index
            
            # 将输入框挂载到ValueOptionsPanel本身
            self.mount(value_input)
            value_input.focus()
    
    def action_cancel_edit(self) -> None:
        """按esc键取消编辑，返回导航模式"""
        if self.editing_index is not None and self.editing_input is not None:
            # 移除输入框
            self.editing_input.remove()
            self.editing_input = None
            self.editing_index = None
            
            # 重新显示ValueOptionsPanel的所有子项
            for child in self.children:
                if isinstance(child, ValueOptionItem):
                    child.display = True
            
            # 将焦点返回到ListView
            self.focus()
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """当输入框提交时，保存值并退出编辑模式"""
        # 检查是否是我们的编辑输入框
        if event.input.id == "value_edit_input" and self.editing_index is not None:
            # 阻止事件继续传播
            event.stop()
            
            # 获取输入的值
            new_value = event.input.value
            
            # 保存值
            index = self.editing_index
            opt = self.option_data[index]
            opt_name = opt.long_option or opt.short_option or ''
            self.option_values[opt_name] = new_value
            
            # 更新对应的ValueOptionItem显示
            # 注意：children中现在包含输入框，所以需要找到正确的item
            list_items = [child for child in self.children if isinstance(child, ValueOptionItem)]
            if index < len(list_items):
                item = list_items[index]
                item.value = new_value
                item.value_label.update(f" = {new_value}" if new_value else " = (no value)")
                item.refresh()
            
            # 移除输入框
            event.input.remove()
            self.editing_input = None
            self.editing_index = None
            
            # 重新显示ValueOptionsPanel的所有子项
            for child in self.children:
                if isinstance(child, ValueOptionItem):
                    child.display = True
            
            # 直接调用app的update_preview方法以更新preview
            # 因为值已经改变，需要立即更新preview
            try:
                app = self.app
                if hasattr(app, 'update_preview'):
                    app.update_preview()
            except:
                pass
            
            # 触发checkbox变化事件以更新preview（双重保险）
            from textual.widgets import Checkbox
            if index < len(list_items):
                item = list_items[index]
                item.checkbox.post_message(Checkbox.Changed(item.checkbox, item.checkbox.value))
            
            # 将焦点返回到ListView，并确保index正确
            # 使用call_later确保在输入框完全移除后再设置焦点
            self.call_later(self.focus)
            # 确保index仍然指向正确的项
            if index < len(list_items):
                self.index = index
    
    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """当选中项变化时，发送消息更新description"""
        # 如果正在编辑，不处理选择事件（避免与enter键冲突）
        if self.editing_index is not None:
            return
        
        index = self.index
        if index is not None and index in self.option_data:
            opt = self.option_data[index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
    
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """当高亮项变化时（使用j/k导航），也更新description"""
        index = self.index
        if index is not None and index in self.option_data:
            opt = self.option_data[index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
    
    def on_focus(self, event) -> None:
        """当窗口获得焦点时，更新description"""
        index = self.index
        if index is not None and index in self.option_data:
            opt = self.option_data[index]
            description = opt.description or 'No description available.'
            self.post_message(OptionSelected(description))
