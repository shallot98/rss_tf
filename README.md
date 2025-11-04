# RSS监控程序

支持多RSS源监控，可以监控多个RSS源的更新并通过Telegram发送通知。

## 功能特性

- **多RSS源支持** - 支持同时监控多个RSS源
- **独立关键词配置** - 每个RSS源可以配置独立的关键词列表
- **🎯 按钮式管理** - 完全通过Telegram按钮管理RSS源和关键词，无需记忆命令
- **内联键盘界面** - 友好的内联键盘按钮，可视化管理RSS源和关键词
- **增强智能去重** - 多层去重机制，彻底解决重复推送问题
  - 稳定的去重键生成（entry.id > guid > 标准化链接）
  - URL标准化（移除跟踪参数、排序查询参数）
  - 时间窗口防抖（可配置）
  - 单次循环单发保护
  - 持久化历史支持重启
- **自动重启** - 定期自动重启释放内存
- **后台运行** - 支持后台运行，进程管理
- **Docker支持** - 优化的Docker镜像，资源占用低
- **日志轮转** - 自动日志管理和清理
- **调试模式** - 详细的去重决策日志

## 快速开始

### 方法一：使用启动向导（推荐）

1. 运行启动向导：
   ```bash
   python3 start.py
   ```

2. 按照向导提示配置Telegram机器人信息

3. 添加RSS源并配置关键词

4. 启动监控程序（程序将在后台运行）

5. 通过Telegram指令管理源和关键词

### 方法二：Docker运行

1. 编辑 `.env` 文件配置环境变量：
   ```env
   TG_BOT_TOKEN=your_bot_token
   TG_CHAT_ID=your_chat_id
   ```

2. 启动容器：
   ```bash
   docker compose up -d
   ```

3. 通过Telegram指令管理RSS源和关键词

### 方法三：手动运行

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量
export TG_BOT_TOKEN=your_bot_token
export TG_CHAT_ID=your_chat_id

# 运行监控程序
python3 rss_main.py
```

## Telegram机器人配置

1. 在Telegram中搜索 `@BotFather`
2. 发送 `/newbot` 创建新机器人
3. 按照提示设置机器人名称
4. 获取 `bot_token`（类似：123456789:ABCdefGHIjklMNOpqrsTUVwxyz）
5. 将机器人添加到群组或直接与机器人对话
6. 获取 `chat_id`（群组ID或个人ID）

## 🎯 按钮式管理（推荐）

### 快速入门

发送 `/manage` 或 `/listsources` 即可打开按钮管理界面，所有操作都可以通过点击按钮完成！

### 主要功能

#### 📱 RSS源管理
- **查看所有RSS源**：点击按钮查看源详情
- **➕ 添加新RSS源**：
  1. 点击"➕ 添加新RSS源"按钮
  2. 发送RSS源的URL
  3. 发送RSS源的名称
  4. 完成！
- **🗑️ 删除RSS源**：
  1. 进入源详情页
  2. 点击"🗑️ 删除此源"按钮
  3. 确认删除

#### 🏷️ 关键词管理
- **查看关键词列表**：在源详情页查看所有关键词
- **➕ 添加关键词**：
  1. 点击"➕ 添加关键词"按钮
  2. 发送要添加的关键词
  3. 完成！
- **❌ 删除关键词**：直接点击关键词旁的删除按钮

### 特点
- ✅ 无需记忆复杂命令
- ✅ 直观的操作流程
- ✅ 自动验证输入
- ✅ 支持随时取消操作
- ✅ 实时显示操作结果

详细使用指南请查看：[按钮管理指南](BUTTON_MANAGEMENT_GUIDE.md)

## ⌨️ 命令行管理（备用）

如果你更喜欢命令行操作，所有功能仍然可以通过命令使用。

### 源管理指令

#### `/addsource <url> <name>` - 添加RSS源
- **功能**：添加新的RSS源
- **用法**：`/addsource <RSS源URL> <源名称>`
- **示例**：`/addsource https://rss.nodeseek.com/ NodeSeek`
- **说明**：源名称将自动转换为小写ID，空格替换为下划线

#### `/delsource <name>` - 删除RSS源
- **功能**：删除已配置的RSS源
- **用法**：`/delsource <源名称或ID>`
- **示例**：`/delsource NodeSeek` 或 `/delsource nodeseek`
- **说明**：删除源时会同时删除该源的所有关键词和历史记录

#### `/listsources` 或 `/manage` - 打开管理面板
- **功能**：以内联键盘按钮形式显示管理界面
- **用法**：直接发送 `/listsources` 或 `/manage`
- **返回**：所有RSS源按钮 + "➕ 添加新RSS源"按钮
- **操作**：
  - 点击源按钮查看详情和管理关键词
  - 点击"➕ 添加新RSS源"按钮添加新源
  - 所有添加/删除操作都可通过按钮完成
  - 点击"返回源列表"按钮回到源列表

### 关键词管理指令

#### `/add <source_name> <keyword>` - 添加关键词
- **功能**：为指定源添加关键词
- **用法**：`/add <源名称或ID> <关键词>`
- **示例**：`/add NodeSeek VPS`、`/add nodeseek 服务器`
- **特点**：不区分大小写，自动去重

#### `/del <source_name> <keyword>` - 删除关键词
- **功能**：删除指定源的关键词
- **用法**：`/del <源名称或ID> <关键词>`
- **示例**：`/del NodeSeek VPS`
- **特点**：不区分大小写，删除所有匹配项

#### `/list <source_name>` - 查看指定源的关键词
- **功能**：显示指定源的所有关键词
- **用法**：`/list <源名称或ID>`
- **示例**：`/list NodeSeek`
- **返回**：编号的关键词列表

#### `/list` - 查看所有源的关键词
- **功能**：显示所有源及其关键词
- **用法**：直接发送 `/list`
- **返回**：按源分组的关键词列表

#### `/help` - 查看帮助
- **功能**：显示所有可用指令的说明
- **用法**：直接发送 `/help`

## 内联键盘使用指南

程序支持友好的内联键盘界面，让RSS源和关键词管理更加直观便捷。

### 使用步骤

1. **打开RSS源列表**
   - 发送 `/listsources` 命令
   - 机器人会显示所有RSS源，每个源一个按钮
   - 按钮显示格式：`📡 源名称 (X个关键词)`

2. **查看源详情和关键词**
   - 点击任意一个RSS源按钮
   - 显示源的详细信息：名称、ID、URL
   - 列出该源的所有关键词（带编号）
   - 显示管理提示（如何添加/删除关键词）

3. **删除关键词**
   - 在源详情页面，每个关键词都有一个删除按钮
   - 按钮格式：`❌ 删除: 关键词内容`
   - 点击即可删除对应的关键词
   - 删除后页面自动刷新，显示最新状态

4. **返回源列表**
   - 点击底部的 `🔙 返回源列表` 按钮
   - 返回到RSS源列表页面

### 内联键盘优势

- **可视化操作** - 无需记住复杂的命令语法
- **即时反馈** - 操作后立即看到结果
- **防止误操作** - 删除操作有明确的按钮标识
- **导航便捷** - 在不同页面间轻松切换

### 结合传统命令

内联键盘和传统命令可以同时使用：

- 内联键盘适合：浏览源列表、查看关键词、删除关键词
- 传统命令适合：添加新源、添加关键词（文本输入）

**示例工作流：**
```
1. 用命令添加新源: /addsource https://rss.example.com/ ExampleSite
2. 用命令添加关键词: /add ExampleSite VPS
3. 用 /listsources 打开内联键盘查看所有源
4. 点击按钮浏览和管理关键词
5. 点击按钮删除不需要的关键词
```

## 配置文件结构

程序会在 `data/config.json` 中保存配置：

```json
{
  "telegram": {
    "bot_token": "YOUR_BOT_TOKEN",
    "chat_id": "YOUR_CHAT_ID"
  },
  "rss_sources": [
    {
      "id": "nodeseek",
      "name": "NodeSeek",
      "url": "https://rss.nodeseek.com/",
      "keywords": ["VPS", "服务器"],
      "dedup_history": {
        "id:post-123:author:john": 1699999999.123,
        "link:abc123def456:author:jane": 1699999888.456
      },
      "notified_posts": []
    },
    {
      "id": "another_source",
      "name": "Another Source",
      "url": "https://example.com/rss",
      "keywords": ["关键词"],
      "dedup_history": {},
      "notified_posts": []
    }
  ],
  "monitor_settings": {
    "check_interval_min": 30,
    "check_interval_max": 60,
    "max_history": 100,
    "restart_after_checks": 100,
    "dedup_history_size": 1000,
    "dedup_debounce_hours": 24,
    "enable_debug_logging": false
  }
}
```

**字段说明：**
- `dedup_history` - 去重历史记录，键为去重键，值为Unix时间戳
- `notified_posts` - 向后兼容的通知记录列表（自动维护）

## 环境变量

Docker运行时可配置以下环境变量：

```bash
TG_BOT_TOKEN          # Telegram机器人Token（必需）
TG_CHAT_ID            # Telegram聊天ID（必需）
CHECK_MIN_INTERVAL    # 最小检查间隔（秒，默认30）
CHECK_MAX_INTERVAL    # 最大检查间隔（秒，默认60）
TZ                    # 时区设置（默认Asia/Shanghai）
```

## Docker部署优化

### 镜像特性
- 基于 `python:3.9-slim` 最小化镜像
- 多阶段构建减少层数
- 清理缓存降低镜像大小
- 优化的依赖安装

### 资源限制
- 内存限制：256MB（保留128MB）
- CPU限制：0.5核（保留0.25核）
- 健康检查：60秒间隔检查进程状态

### 构建镜像
```bash
docker build -t rss_monitor:latest .
```

### 运行容器
```bash
docker compose up -d
```

### 查看日志
```bash
docker compose logs -f
```

## 依赖包

- `requests>=2.25.0` - HTTP请求库
- `feedparser>=6.0.0` - RSS解析库
- `psutil>=5.8.0` - 系统监控库

## 系统要求

- **Python版本**：3.7或更高版本
- **操作系统**：Windows、Linux、macOS
- **网络连接**：需要访问RSS源和Telegram API
- **磁盘空间**：至少100MB可用空间
- **内存**：建议至少256MB可用内存

## 监控流程

1. 程序启动，加载配置文件
2. 启动Telegram指令监听线程
3. 进入监控循环：
   - 遍历所有配置的RSS源
   - 对每个源：
     - 获取并解析RSS内容
     - 使用该源的关键词过滤
     - 独立去重检查
     - 发送Telegram通知
   - 随机等待后进行下一轮检查
4. 达到检查次数上限后自动重启

## 进程管理

### 使用start.py管理
- **启动**：在start.py菜单中选择"启动监控程序"
- **停止**：在start.py菜单中选择"停止监控程序"
- **状态**：在start.py菜单中选择"查看监控状态"

### 手动管理
```bash
# 查看进程（Windows）
tasklist | findstr python

# 查看进程（Linux/macOS）
ps aux | grep rss_main.py

# 停止进程（Windows）
taskkill /PID <进程ID> /F

# 停止进程（Linux/macOS）
kill <进程ID>
```

## 日志文件

- **程序日志**：`data/monitor.log`
- **日志轮转**：单文件最大5MB，保留1个备份
- **配置文件**：`data/config.json`
- **配置备份**：`data/config.json.bak`
- **进程ID**：`data/monitor.pid`

## 注意事项

1. **多源配置**：每个RSS源必须配置独立的关键词才会开始监控
2. **源ID唯一性**：源ID必须唯一，重复的源ID会导致冲突
3. **关键词管理**：建议通过Telegram指令管理，实时生效
4. **去重机制**：每个源独立维护去重记录，不会相互影响
5. **内存管理**：程序会定期重启以释放内存
6. **Docker部署**：推荐使用Docker运行，资源占用更低
7. **网络稳定性**：需要稳定的网络访问RSS源和Telegram API

## 去重机制详解

### 去重策略

程序采用多层去重机制，确保同一RSS项不会被重复推送：

#### 1. 稳定的去重键生成

**优先级顺序：**
1. **entry.id** - RSS/Atom标准ID字段（最高优先级）
2. **entry.guid** - RSS GUID字段
3. **标准化链接 + 作者** - 作为后备方案

**链接标准化处理：**
- 协议和域名转为小写
- 移除跟踪参数（utm_*, fbclid, gclid等）
- 查询参数排序
- 移除URL片段（#部分）
- 移除路径尾部斜杠

**示例：** 这两个URL会生成相同的去重键：
```
https://NodeSeek.COM/post-123?utm_source=twitter&id=1#comments
https://nodeseek.com/post-123?id=1&utm_source=facebook
```

#### 2. 时间窗口防抖（Debounce）

- 默认24小时防抖窗口
- 在窗口期内，相同的项会被抑制
- 超过窗口期的旧项可以重新推送（允许推送更新或重要信息）
- 窗口期外的旧记录会被自动清理以节省内存

#### 3. 单次循环单发保护

- 每个检查循环维护已发送集合
- 即使一个项匹配多个关键词，也只发送一次通知

#### 4. 持久化历史

- 历史记录包含时间戳，支持重启后恢复
- 原子写入机制（fsync + 原子重命名）
- 自动从损坏的历史文件恢复
- 限制历史大小（默认1000条）
- 自动清理超出防抖窗口的旧记录

### 配置选项

在 `monitor_settings` 中可配置以下去重参数：

```json
{
  "monitor_settings": {
    "dedup_history_size": 1000,        // 最大历史记录数（默认1000）
    "dedup_debounce_hours": 24,        // 防抖窗口小时数（默认24）
    "enable_debug_logging": false      // 启用详细去重日志（默认false）
  }
}
```

**参数说明：**

- `dedup_history_size` - 去重历史记录的最大条目数
  - 建议值：500-2000
  - 太小：可能导致旧项被遗忘后重新推送
  - 太大：占用更多内存

- `dedup_debounce_hours` - 防抖窗口（小时）
  - 建议值：24-72
  - 在此时间内，相同项不会重复推送
  - 超过此时间的历史记录会被清理

- `enable_debug_logging` - 调试日志开关
  - 启用后会详细记录每个项的去重决策过程
  - 包括：去重键、标准化链接、决策原因等
  - 仅在排查问题时启用

### 调试模式

启用调试日志来排查去重问题：

1. 编辑 `data/config.json`，在 `monitor_settings` 中添加：
   ```json
   "enable_debug_logging": true
   ```

2. 查看日志 `data/monitor.log`，会看到类似信息：
   ```
   [源名称] Entry analysis:
     Title: 示例帖子标题
     Link: https://example.com/post-123
     Author: 作者名
     Dedup key: id:post-123:author:authorname
     Key type: entry_id
     Normalized link: https://example.com/post-123
   ```

3. 对于重复项，会看到：
   ```
   [源名称] ⏭️ 跳过重复项: id:post-123:author:authorname (debounced (2.5h ago))
   ```

### 向后兼容性

- 自动从旧的 `notified_posts` 列表格式迁移到新的时间戳历史
- 迁移时假设旧记录是"刚看到的"，避免重新推送
- 新旧格式同时保存，确保版本回退时数据不丢失

## 故障排除

### 重复推送问题

如果仍然收到重复通知：

1. **启用调试日志**：在配置中设置 `enable_debug_logging: true`
2. **检查去重键**：查看日志中的 `Dedup key`，确认相同帖子生成的键是否一致
3. **检查防抖窗口**：确认 `dedup_debounce_hours` 设置合理（建议24-48小时）
4. **清理旧历史**：如果怀疑历史文件损坏：
   ```bash
   # 备份当前配置
   cp data/config.json data/config.json.backup
   
   # 编辑配置，删除所有源的 dedup_history 和 notified_posts 字段
   # 或者直接重启程序让它重新建立历史
   ```

### 配置文件损坏
- 检查 `data/config.json.bak` 备份文件
- 程序会自动尝试从备份恢复
- 如果备份也损坏，删除配置文件重新初始化（会丢失历史记录）

### 通知不工作
- 检查bot_token和chat_id是否正确
- 确认RSS源是否可访问
- 检查关键词是否已配置
- 查看 `data/monitor.log` 中的错误信息

### 进程无法停止
- 检查 `data/monitor.pid` 文件
- 手动结束进程
- 删除 PID 文件后重新启动

### Docker容器异常
```bash
# 查看容器日志
docker compose logs -f

# 重启容器
docker compose restart

# 重新构建
docker compose down
docker compose up -d --build
```

### 历史文件损坏恢复

程序会自动从历史文件损坏中恢复，但如需手动干预：

```bash
# 1. 停止监控程序
python3 start.py  # 选择停止选项

# 2. 备份当前配置
cp data/config.json data/config.json.manual_backup

# 3. 编辑 config.json，移除损坏的 dedup_history 字段
# 或使用备份文件
cp data/config.json.bak data/config.json

# 4. 重启程序
python3 start.py  # 选择启动选项
```

## 项目特点

- **灵活架构**：支持任意数量的RSS源，每个源独立配置
- **实时管理**：通过Telegram指令实时管理源和关键词
- **智能去重**：每个源独立去重，避免误判
- **资源优化**：自动内存清理和进程重启
- **Docker优化**：最小化镜像，合理的资源限制
- **生产就绪**：完整的错误处理和日志记录
- **易于使用**：友好的配置向导和详细文档
- **跨平台**：支持Windows、Linux、macOS

## 版本信息

- **当前版本**：2.2
- **主要更新**：
  - 🎨 新增内联键盘界面，可视化管理RSS源和关键词
  - 🖱️ 点击按钮即可查看源详情和管理关键词
  - ❌ 一键删除关键词，操作更便捷
  - 🔄 支持页面间流畅导航
  - 📱 更友好的移动端体验

- **版本2.1**：
  - ✨ 全面重构去重逻辑，修复重复推送问题
  - 🔑 稳定的去重键生成（entry.id > guid > 标准化链接）
  - 🔗 智能URL标准化（移除跟踪参数、查询参数排序）
  - ⏰ 时间窗口防抖机制（默认24小时）
  - 💾 带时间戳的持久化历史
  - 🔒 原子写入配置文件（fsync + 原子重命名）
  - 🛡️ 历史文件损坏自动恢复
  - 🔍 详细的调试日志模式
  - ✅ 36个单元测试覆盖核心功能
  - 🔄 向后兼容旧配置格式

- **版本2.0**：
  - 支持多RSS源
  - 每个源独立关键词配置
  - Telegram源管理命令
  - Docker镜像优化
  - 代码架构重构

## 技术支持

如果遇到问题，请检查：

1. Python版本是否满足要求（3.7+）
2. 网络连接是否正常
3. Telegram配置是否正确
4. RSS源URL是否有效
5. 关键词是否已配置
6. 日志文件中的错误信息
