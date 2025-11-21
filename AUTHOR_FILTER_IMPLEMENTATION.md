# RSS 作者过滤功能实现文档

## 概述

为 rss_tf 项目添加了完整的作者监控过滤功能，包括配置管理、Telegram 命令和内联键盘操作界面。

## 实现内容

### 1. 配置架构更新

在每个 RSS 源的配置中扩展了以下字段：

```json
{
  "author_whitelist": [],      // 作者白名单
  "author_blacklist": [],      // 作者黑名单
  "author_match_mode": "contains"  // 匹配模式：exact 或 contains
}
```

- **author_whitelist**: 作者白名单列表，如果配置了白名单，只有白名单中的作者才会被推送
- **author_blacklist**: 作者黑名单列表，黑名单中的作者会被过滤掉
- **author_match_mode**: 匹配模式
  - `contains`: 部分匹配（默认），作者名包含过滤器或过滤器包含作者名即匹配
  - `exact`: 精确匹配，作者名必须完全一致才匹配

### 2. RSS 过滤逻辑

#### 作者提取
在 `check_rss_feed` 函数中，已有代码从多个可能的字段提取作者信息：
- `entry.author`
- `entry.author_detail.name`
- `entry.dc_creator`
- `entry.summary` 中的"作者："标签
- `entry.tags` 中的作者标签

#### 过滤逻辑实现

添加了两个核心函数：

1. **check_author_match(author, filter_list, match_mode)**
   - 检查作者是否匹配过滤列表
   - 支持大小写不敏感匹配
   - 支持 exact 和 contains 两种模式

2. **should_filter_by_author(author, source)**
   - 判断是否应该根据作者过滤掉此条目
   - 实现白名单优先逻辑
   - 返回 (should_skip, reason) 元组

#### 过滤优先级

1. 首先进行关键词匹配
2. 关键词匹配后进行作者过滤（AND 逻辑）
3. 白名单优先：如果配置了白名单，只允许白名单中的作者
4. 白名单作者仍需检查黑名单（白名单且在黑名单中的作者会被过滤）
5. 如果只配置黑名单，则排除黑名单中的作者
6. 空作者或作者信息缺失：如果配置了白名单，会被过滤掉

### 3. Telegram 命令扩展

#### 基础命令

- `/add_author <source_name> <author_name>` - 添加作者到白名单
- `/del_author <source_name> <author_name>` - 从白名单删除作者
- `/add_author_blacklist <source_name> <author_name>` - 添加作者到黑名单
- `/del_author_blacklist <source_name> <author_name>` - 从黑名单删除作者
- `/list_authors <source_name>` - 查看作者过滤设置
- `/manage_authors <source_name>` - 打开作者管理内联键盘界面

#### 命令特性

- 所有命令支持大小写不敏感匹配
- 自动检查重复项
- 提供清晰的错误提示
- 修改后配置立即生效，无需重启

### 4. 内联键盘界面设计

#### 源管理界面增强
在每个 RSS 源的详情页面添加了"👤 作者管理"按钮，可直接进入作者管理界面。

#### 作者管理主菜单
使用 `/manage_authors <source_name>` 或点击"作者管理"按钮进入：

```
👤 作者过滤管理 - [源名称]

当前匹配模式: contains
白名单作者数: 2
黑名单作者数: 1

选择操作：
[🤍 查看白名单]
[🚫 查看黑名单]
[➕ 添加白名单作者]
[➕ 添加黑名单作者]
[🔄 切换匹配模式 (当前: contains)]
[🔙 返回源管理]
```

#### 查看白名单/黑名单界面

```
🤍 白名单作者 - [源名称]

• 作者1
  [❌ 作者1]
• 作者2
  [❌ 作者2]

[➕ 添加白名单作者]
[🔙 返回作者管理]
```

- 每个作者旁边都有删除按钮
- 长作者名会被截断显示（超过30字符显示省略号）
- 点击删除按钮会显示确认对话框

#### 添加作者流程

1. 点击"添加白名单作者"或"添加黑名单作者"
2. Bot 提示输入作者名称
3. 用户直接回复作者名称
4. Bot 自动保存并更新显示
5. 提供"取消"按钮可随时退出

#### 删除作者流程

1. 在列表中点击作者旁的 ❌ 按钮
2. 显示确认对话框：
   ```
   ⚠️ 确认删除白名单作者
   
   确定要从白名单中删除作者 [作者名] 吗？
   
   [✅ 确认删除]
   [❌ 取消]
   ```
3. 确认后删除并更新列表

#### 切换匹配模式

点击"🔄 切换匹配模式"按钮可在 `contains` 和 `exact` 之间切换，立即生效。

### 5. 回调处理

实现了以下 callback_data 处理：

- `author_menu:<source_id>` - 显示作者管理主菜单
- `view_whitelist:<source_id>` - 查看白名单
- `view_blacklist:<source_id>` - 查看黑名单
- `add_whitelist:<source_id>` - 开始添加白名单作者流程
- `add_blacklist:<source_id>` - 开始添加黑名单作者流程
- `del_whitelist:<source_id>:<author>` - 删除白名单作者（显示确认）
- `del_blacklist:<source_id>:<author>` - 删除黑名单作者（显示确认）
- `confirm_del_whitelist:<source_id>:<author>` - 确认删除白名单作者
- `confirm_del_blacklist:<source_id>:<author>` - 确认删除黑名单作者
- `cancel_author_input:<source_id>` - 取消作者输入流程
- `toggle_match_mode:<source_id>` - 切换匹配模式

### 6. 用户状态管理

新增了两个用户状态：

- `waiting_for_whitelist_author` - 等待用户输入白名单作者名称
- `waiting_for_blacklist_author` - 等待用户输入黑名单作者名称

状态数据包含：
- `source_id`: 当前操作的源 ID
- `message_id`: 原始消息 ID（用于编辑消息）

### 7. 配置向后兼容

- 旧配置文件加载时自动为所有源添加默认的作者过滤字段
- 新建源时自动初始化作者过滤字段
- 不会影响现有功能

## 技术细节

### 作者匹配算法

```python
def check_author_match(author, filter_list, match_mode='contains'):
    """
    检查作者是否匹配过滤列表
    
    - 大小写不敏感（全部转为小写比较）
    - contains 模式：双向包含匹配
    - exact 模式：完全相等匹配
    """
```

### 过滤决策逻辑

```python
def should_filter_by_author(author, source):
    """
    过滤决策：
    
    1. 无任何过滤配置 → 放行
    2. 有白名单：
       - 作者为空 → 过滤
       - 在白名单中：
         - 不在黑名单 → 放行
         - 在黑名单 → 过滤
       - 不在白名单 → 过滤
    3. 只有黑名单：
       - 在黑名单 → 过滤
       - 不在黑名单 → 放行
    """
```

### 消息编辑机制

使用 `edit_telegram_message` 函数编辑现有消息，避免发送大量新消息：
- 所有界面跳转都通过编辑消息实现
- 保持用户界面清晰
- 减少聊天记录混乱

### 安全性考虑

- 所有用户输入都进行 trim() 处理
- 重复项检查（大小写不敏感）
- 确认对话框防止误操作
- 配置原子写入带 fsync 保证数据完整性

## 使用示例

### 场景1：只关注特定作者

```
/manage_authors NodeSeek
→ 点击"添加白名单作者"
→ 输入: 张三
→ 点击"添加白名单作者"
→ 输入: 李四
```

此时只有张三和李四的帖子（且匹配关键词）才会被推送。

### 场景2：排除垃圾发帖者

```
/manage_authors NodeSeek
→ 点击"添加黑名单作者"
→ 输入: 广告用户
```

此时"广告用户"的帖子将被过滤，其他作者正常推送。

### 场景3：精确匹配模式

```
/manage_authors NodeSeek
→ 点击"切换匹配模式"
→ 模式变为: exact
```

此时必须作者名完全匹配才会生效，避免误匹配。

### 场景4：命令行快速操作

```
# 添加白名单
/add_author NodeSeek 张三

# 添加黑名单
/add_author_blacklist NodeSeek 广告用户

# 查看设置
/list_authors NodeSeek

# 删除
/del_author NodeSeek 张三
```

## 测试建议

1. **基础功能测试**
   - 添加/删除白名单作者
   - 添加/删除黑名单作者
   - 切换匹配模式
   - 查看作者列表

2. **过滤逻辑测试**
   - 只配置白名单的过滤效果
   - 只配置黑名单的过滤效果
   - 同时配置白名单和黑名单的效果
   - 空作者的处理
   - 作者名大小写变化的匹配

3. **UI/UX 测试**
   - 内联键盘按钮响应
   - 消息编辑而非新建
   - 长作者名的显示
   - 确认对话框的显示和取消

4. **边界情况测试**
   - 重复添加同一作者
   - 删除不存在的作者
   - 源不存在时的错误处理
   - 用户输入为空时的处理

## 验收检查清单

- [x] 配置文件支持作者过滤字段
- [x] 配置正确持久化到 config.json
- [x] RSS 过滤逻辑能准确识别作者并应用过滤
- [x] 白名单和黑名单逻辑正确（白名单优先）
- [x] 作者过滤与关键词过滤正确配合（AND 逻辑）
- [x] 空作者或作者信息缺失的条目处理正确
- [x] Telegram 命令能正确添加/删除/查看作者
- [x] `/manage_authors` 命令显示作者管理主菜单
- [x] 内联键盘按钮能正确响应用户点击
- [x] 查看白名单/黑名单能正确显示当前作者列表
- [x] 添加作者流程能正确接收用户输入并保存
- [x] 删除作者按钮能正确删除指定作者
- [x] 删除前有确认对话，防止误操作
- [x] 返回菜单按钮能正确导航
- [x] 命令方式和内联键盘操作的数据保持同步
- [x] UI 界面清晰、按钮标签易于理解
- [x] 支持编辑消息更新界面（而不是每次都发送新消息）
- [x] 配置变更后无需重启立即生效
- [x] 作者匹配不区分大小写
- [x] 支持部分匹配（contains）和精确匹配（exact）两种模式
- [x] 对长作者名称进行截断处理（显示省略号）
- [x] 旧配置向后兼容

## 更新的文件

- `rss_main.py` - 主程序文件，包含所有新功能

## 新增功能概览

1. **配置字段**: 3个新字段（author_whitelist, author_blacklist, author_match_mode）
2. **核心函数**: 2个（check_author_match, should_filter_by_author）
3. **Telegram 命令**: 6个
4. **回调处理**: 11个 callback_data 类型
5. **用户状态**: 2个新状态
6. **UI 界面**: 作者管理完整界面流程

## 注意事项

1. 配置变更后立即生效，无需重启监控进程
2. 作者过滤在关键词过滤之后执行（AND 逻辑）
3. 白名单优先于黑名单
4. 作者名匹配不区分大小写
5. 长作者名在按钮中会被截断但在消息文本中完整显示
