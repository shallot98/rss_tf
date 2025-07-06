# RSS监控程序

这是一个RSS监控程序，可以监控RSS源的更新并通过Telegram发送通知。

## 功能特性

- RSS源监控
- 关键词过滤
- Telegram通知
- 自动去重
- 日志记录
- 配置文件管理
- 友好的配置向导
- Telegram指令管理关键词
- **后台运行支持**
- **进程管理功能**

## 快速开始

### 方法一：使用启动向导（推荐）

1. 双击运行 `run.bat`
2. 按照向导提示配置Telegram机器人信息
3. 启动监控程序（程序将在后台运行）
4. 通过Telegram指令管理关键词
5. **重要**：start.py退出后，监控程序仍会继续在后台运行

### 方法二：手动运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行启动向导
python3 start.py

# 或直接运行监控程序（需要先配置环境变量）
python3 rss_main.py
```


### 方法三：Docker运行

下载或创建`docker-compose.yml`、`.env`文件

编辑好`.env`配置内容

一键启动：

```
docker compose up -d
```



## 配置说明

### Telegram机器人配置

1. 在Telegram中搜索 `@BotFather`
2. 发送 `/newbot` 创建新机器人
3. 按照提示设置机器人名称
4. 获取 `bot_token`（类似：123456789:ABCdefGHIjklMNOpqrsTUVwxyz）
5. 将机器人添加到群组或直接与机器人对话
6. 获取 `chat_id`（群组ID或个人ID）

### 关键词管理

**通过Telegram指令管理关键词**（推荐方式）：

- `/add 关键词` - 添加关键词
- `/del 关键词` - 删除关键词
- `/list` - 查看所有关键词
- `/help` - 查看帮助

### 环境变量

程序支持通过环境变量配置：

```bash
# Windows
set TG_BOT_TOKEN=your_bot_token
set TG_CHAT_ID=your_chat_id

# Linux/macOS
export TG_BOT_TOKEN=your_bot_token
export TG_CHAT_ID=your_chat_id
```

## 配置文件

程序会在 `data/config.json` 中保存配置：

```json
{
    "keywords": ["关键词1", "关键词2"],
    "notified_entries": {},
    "telegram": {
        "bot_token": "YOUR_BOT_TOKEN",
        "chat_id": "YOUR_CHAT_ID"
    }
}
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

## 使用说明

### 启动向导功能

1. **配置Telegram机器人**：设置bot_token和chat_id
2. **查看当前配置**：显示当前所有配置信息
3. **启动监控程序**：在后台启动RSS监控
4. **停止监控程序**：停止后台运行的监控程序
5. **查看监控状态**：检查监控程序是否正在运行
6. **退出**：退出配置向导（监控程序继续运行）

### 监控程序功能

- 自动监控RSS源更新
- 根据关键词过滤内容
- 通过Telegram发送通知
- 自动去重避免重复通知
- 完整的日志记录
- **后台运行**：start.py退出后仍继续运行

### 进程管理

程序提供完整的进程管理功能：

- **后台启动**：监控程序在后台运行，不占用当前终端
- **进程检查**：自动检查监控程序是否正在运行
- **优雅停止**：支持优雅停止监控程序
- **PID文件**：保存进程ID到`data/monitor.pid`
- **状态查看**：实时查看监控程序运行状态

### Telegram指令详解

在Telegram中可以向机器人发送以下指令：

#### `/add 关键词` - 添加关键词
- **功能**：添加要监控的关键词
- **用法**：`/add 关键词名称`
- **示例**：`/add 服务器`、`/add VPS`
- **特点**：不区分大小写，自动去重

#### `/del 关键词` - 删除关键词
- **功能**：删除已设置的关键词
- **用法**：`/del 关键词名称`
- **示例**：`/del 服务器`
- **特点**：不区分大小写，删除所有匹配项

#### `/list` - 查看关键词列表
- **功能**：显示当前所有设置的关键词
- **用法**：直接发送 `/list`
- **返回**：编号的关键词列表

#### `/help` - 查看帮助
- **功能**：显示所有可用指令的说明
- **用法**：直接发送 `/help`

## 注意事项

1. **Telegram配置**：需要创建Telegram机器人并获取bot_token和chat_id
2. **RSS源**：程序默认监控NodeSeek的RSS源
3. **权限**：确保有足够的权限创建目录和文件
4. **网络**：程序需要稳定的网络连接
5. **关键词管理**：建议通过Telegram指令管理关键词，更加方便
6. **后台运行**：start.py退出后监控程序仍会继续运行，需要手动停止
7. **进程管理**：使用start.py的进程管理功能来启动/停止监控程序

## 故障排除

### 常见问题

1. **Python未安装**：从Python官网下载并安装Python 3.7+
2. **依赖安装失败**：检查网络连接，尝试使用国内镜像源
3. **Telegram通知失败**：检查bot_token和chat_id是否正确
4. **配置文件错误**：删除data目录重新配置
5. **进程无法停止**：检查PID文件是否存在，或手动结束进程

### 日志文件

- 程序日志：`data/monitor.log`
- 配置文件：`data/config.json`
- 进程ID：`data/monitor.pid`

### 手动进程管理

如果start.py的进程管理功能出现问题，可以手动管理：

```bash
# 查看进程
tasklist | findstr python  # Windows
ps aux | grep rss_main.py  # Linux/macOS

# 停止进程
taskkill /PID <进程ID> /F  # Windows
kill <进程ID>              # Linux/macOS
```

## 项目特点

- **完整功能**：包含完整的RSS监控和通知功能
- **生产就绪**：具备错误处理、日志记录、配置管理等功能
- **易于使用**：提供友好的配置向导和详细文档
- **跨平台**：支持Windows、Linux、macOS
- **智能管理**：通过Telegram指令管理关键词，无需手动编辑配置文件
- **后台运行**：支持后台运行，start.py退出后监控程序继续工作
- **进程管理**：完整的进程启动、停止、状态检查功能
- **可扩展**：代码结构清晰，易于扩展新功能

## 技术支持

如果遇到问题，请检查：

1. Python版本是否满足要求
2. 网络连接是否正常
3. Telegram配置是否正确
4. 系统权限是否足够
5. 进程管理功能是否正常工作
