# 滚动条样式修复 - 与边框融为一体

## 需求

让所有窗口的滚动条（如果有）和右侧的border融为一体。

## 实现方案

### 1. 滚动条颜色与边框颜色一致

- 默认状态：滚动条颜色使用边框颜色 `#4fd1c5`（青色）
- 焦点状态：滚动条颜色使用焦点边框颜色 `#f6e05e`（黄色）

### 2. 滚动条样式设置

在CSS中添加了以下样式：

```css
/* 滚动条样式 - 与边框融为一体 */
Scrollbar {
    color: #4fd1c5;
    background: transparent;
    width: 1;
}

/* 滚动条滑块样式 */
Scrollbar > .scrollbar-thumb {
    color: #4fd1c5;
    background: #4fd1c5;
}

/* ListView的滚动条样式 */
ListView {
    scrollbar-color: #4fd1c5;
    scrollbar-color-active: #4fd1c5;
    scrollbar-background: transparent;
}

/* 获得焦点时，滚动条颜色也改变 */
ListView:focus-within {
    scrollbar-color: #f6e05e;
    scrollbar-color-active: #f6e05e;
}

/* 各个组件的焦点状态滚动条样式 */
ListView:focus-within Scrollbar {
    color: #f6e05e;
}

ListView:focus-within Scrollbar > .scrollbar-thumb {
    color: #f6e05e;
    background: #f6e05e;
}

Browser:focus-within Scrollbar {
    color: #f6e05e;
}

Browser:focus-within Scrollbar > .scrollbar-thumb {
    color: #f6e05e;
    background: #f6e05e;
}

#short_options:focus-within Scrollbar,
#long_options:focus-within Scrollbar,
#value_options:focus-within Scrollbar {
    color: #f6e05e;
}

#short_options:focus-within Scrollbar > .scrollbar-thumb,
#long_options:focus-within Scrollbar > .scrollbar-thumb,
#value_options:focus-within Scrollbar > .scrollbar-thumb {
    color: #f6e05e;
    background: #f6e05e;
}
```

## 效果

- ✅ 滚动条颜色与边框颜色一致（青色 `#4fd1c5`）
- ✅ 获得焦点时，滚动条颜色与焦点边框颜色一致（黄色 `#f6e05e`）
- ✅ 滚动条背景透明，与边框融为一体
- ✅ 滚动条宽度为1，紧贴右侧边框

## 相关文件

- `style.css` - 添加滚动条样式

## 注意事项

Textual使用自己的CSS方言，某些CSS属性可能不被标准CSS linter识别，但Textual会正确解析这些样式。

