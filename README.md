# RSS监控程序

支持多RSS源监控，可以监控多个RSS源的更新并通过Telegram发送通知。

## 功能特性

- **通用RSS/Atom兼容** - 支持各类RSS 2.0和Atom feeds（Discourse、WordPress、Medium等）
- **多RSS源支持** - 支持同时监控多个RSS源
- **独立关键词配置** - 每个RSS源可以配置独立的关键词列表
- **智能HTTP缓存** - ETag/Last-Modified缓存，节省带宽，避免重复处理
- **Telegram源管理** - 通过Telegram指令管理RSS源和关键词
- **智能去重** - 基于feed内容的稳定去重，跨重启保持一致
- **速率限制处理** - 尊重429/503响应和Retry-After头
- **指数退避重试** - 自动处理临时网络错误
- **自动重启** - 定期自动重启释放内存
- **后台运行** - 支持后台运行，进程管理
- **Docker支持** - 优化的Docker镜像，资源占用低
- **结构化日志** - 详细的HTTP状态、解析错误和匹配日志

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

## Telegram指令详解

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

#### `/listsources` - 列出所有RSS源
- **功能**：显示当前所有配置的RSS源
- **用法**：直接发送 `/listsources`
- **返回**：显示每个源的名称、ID、URL和关键词数量

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
      "notified_posts": [],
      "notified_authors": []
    },
    {
      "id": "another_source",
      "name": "Another Source",
      "url": "https://example.com/rss",
      "keywords": ["关键词"],
      "notified_posts": [],
      "notified_authors": []
    }
  ],
  "monitor_settings": {
    "check_interval_min": 30,
    "check_interval_max": 60,
    "max_history": 100,
    "restart_after_checks": 100,
    "per_feed_min_interval": 60,
    "max_concurrent_feeds": 5,
    "enable_media_links": false
  }
}
```

## 配置说明

### monitor_settings 配置项

- **check_interval_min**: 最小检查间隔（秒），默认30
- **check_interval_max**: 最大检查间隔（秒），默认60
- **max_history**: 每个源保留的去重历史记录数量，默认100
- **restart_after_checks**: 自动重启前的检查次数，默认100
- **per_feed_min_interval**: 每个feed的最小轮询间隔（秒），默认60
- **max_concurrent_feeds**: 同时处理的最大feed数量，默认5
- **enable_media_links**: 是否在通知中包含媒体链接，默认false

示例：
```json
"monitor_settings": {
  "check_interval_min": 30,
  "check_interval_max": 60,
  "max_history": 100,
  "restart_after_checks": 100,
  "per_feed_min_interval": 60,
  "max_concurrent_feeds": 5,
  "enable_media_links": false
}
```

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

## 通用RSS/Atom兼容性

### 支持的Feed格式

程序完全兼容以下feed格式：
- **RSS 2.0** - 传统RSS格式
- **Atom 1.0** - 现代Atom格式
- **混合格式** - 具有扩展字段的RSS/Atom

### 字段提取策略

程序使用智能fallback机制提取feed条目信息：

- **ID**: `entry.id` → `entry.guid` → `entry.link` → `sha1(title + time)`
- **链接**: `entry.link`（优先 `rel="alternate"`）
- **标题**: `entry.title` 或空字符串
- **作者**: `entry.author` → `entry.author_detail.name` → 空字符串
- **时间**: `entry.published_parsed` → `entry.updated_parsed` → None
- **内容**: `entry.content[0].value` → `entry.summary` → `entry.description` → 空字符串
- **媒体**: `entry.enclosures` + `entry.media_content`（可选，默认关闭）

### 去重机制

使用稳定的去重键确保跨重启一致性：

1. **首选**: `{source_host}:{entry_id}`
2. **备选**: `{source_host}:{link}`
3. **最终**: `{source_host}:sha1:{hash(title+time)}`

去重历史持久化到配置文件，重启后继续生效。

### HTTP缓存和速率控制

- **ETag/Last-Modified**: 自动缓存并在请求中发送，支持304响应
- **缓存持久化**: `/data/http_cache.json`，重启后继续使用
- **429/503处理**: 自动识别`Retry-After`头，智能等待
- **指数退避**: 临时错误时使用指数退避+随机jitter
- **Per-feed轮询**: 每个feed独立轮询间隔，避免同时请求
- **并发控制**: 限制同时处理的feed数量（默认5个）

### 关键词匹配

- **仅标题匹配**: 关键词仅在标题中搜索（不包括正文）
- **不区分大小写**: `VPS` 可以匹配 `vps` 或 `Vps`
- **简单子串匹配**: 不支持正则表达式（保持简单）

### 通知格式

Telegram通知包含以下信息：
- 来源名称
- 标题（HTML转义）
- 匹配的关键词
- 作者（如有）
- 发布时间（如有）
- 内容摘要（前200字符，如有）
- 原文链接
- 媒体链接（可选，需启用`enable_media_links`）

消息自动截断到Telegram 4000字符限制。

## 监控流程

1. 程序启动，加载配置文件和HTTP缓存
2. 启动Telegram指令监听线程
3. 进入监控循环：
   - 遍历所有配置的RSS源
   - 对每个源：
     - 检查per-feed最小轮询间隔
     - 发送HTTP请求（带ETag/Last-Modified）
     - 处理304/429/503响应
     - 解析RSS/Atom内容（通用兼容）
     - 使用该源的关键词过滤（仅标题）
     - 独立去重检查（稳定键）
     - 发送Telegram通知（HTML安全）
     - 保存HTTP缓存和去重历史
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

## 故障排除

### 配置文件损坏
- 检查 `data/config.json.bak` 备份文件
- 删除配置文件重新初始化

### 通知不工作
- 检查bot_token和chat_id是否正确
- 确认RSS源是否可访问
- 检查关键词是否已配置

### 进程无法停止
- 检查 `data/monitor.pid` 文件
- 手动结束进程

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

- **当前版本**：3.0
- **主要更新**：
  - 通用RSS/Atom兼容性（支持Discourse、WordPress、Medium等）
  - 智能HTTP缓存（ETag/Last-Modified，304响应）
  - 稳定的去重机制（跨重启一致）
  - 速率限制和Retry-After支持
  - 指数退避重试机制
  - Per-feed轮询间隔和并发控制
  - HTML安全的通知格式
  - 结构化日志记录
- **上一版本（2.0）**：
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
