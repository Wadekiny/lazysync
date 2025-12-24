import os
from functools import wraps
from textual.message import Message
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Union
from textual.containers import Vertical
from textual.widgets import Input, ListView, ListItem, Label, Static
from textual.binding import Binding
from textual.reactive import reactive


class ListViewUI(ListView):
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=True),
        Binding("k", "cursor_up", "Up", show=True),
        Binding("g", "go_first", "First", show=True),
        Binding("G", "go_last", "Last", show=True),
    ]

    def reset_index(self):
        def worker():
            self.index=None
            if len(self.children) > 0:
                self.index = 0
        self.call_later(worker)

    def on_mount(self):
        """挂载时设置默认在第一行"""
        self.reset_index()

    def action_go_first(self):
        """g: 跳转到第一行"""
        self.reset_index()

    def action_go_last(self):
        """G: 跳转到最后一行"""
        def worker():
            if len(self.children) > 0:
                self.index = len(self.children) - 1
        self.call_later(worker)
