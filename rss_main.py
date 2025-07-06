#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import logging
import signal
import subprocess
import feedparser
import requests
import datetime
import re
import random
import gc  # 添加gc库用于主动垃圾回收
import psutil  # 添加psutil库用于监控内存使用
from logging.handlers import RotatingFileHandler
from threading import Thread

# Windows兼容性处理
try:
    import readline
except ImportError:
    pass

try:
    import resource  # Unix/Linux系统资源限制
except ImportError:
    # Windows系统不支持resource模块
    resource = None

# 配置文件和日志文件路径（Windows兼容）
if os.name == 'nt':  # Windows系统
    DATA_DIR = os.path.join(os.getcwd(), 'data')
else:  # Unix/Linux系统
    DATA_DIR = '/data'

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'monitor.log')
PID_FILE = os.path.join(DATA_DIR, 'monitor.pid')

# Windows系统不支持systemd服务
if os.name == 'nt':
    SERVICE_FILE = None
else:
    SERVICE_FILE = '/etc/systemd/system/rss_monitor.service'

# 日志配置
log_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=1)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[log_handler]
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CONFIG = {
    'keywords': [],
    'notified_entries': {},
    'telegram': {
        'bot_token': '',
        'chat_id': ''
    }
}

def load_config():
    """加载配置文件"""
    # 尝试从主配置文件和备份文件加载配置
    config = None
    backup_file = CONFIG_FILE + '.bak'
    
    # 尝试从主配置文件加载
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.debug("从主配置文件加载配置成功")
        except json.JSONDecodeError:
            logger.error("主配置文件JSON格式错误")
            config = None
        except Exception as e:
            logger.error(f"加载主配置文件失败: {e}")
            config = None
    
    # 如果主配置文件加载失败，尝试从备份文件加载
    if config is None and os.path.exists(backup_file):
        try:
            logger.info("主配置文件加载失败，尝试从备份文件加载")
            with open(backup_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info("从备份配置文件加载配置成功")
            # 如果从备份加载成功，则恢复到主配置文件
            save_config(config)
        except Exception as e:
            logger.error(f"从备份配置文件加载失败: {e}")
            config = None
    
    # 如果都失败了，使用默认配置
    if config is None:
        logger.warning("无法加载配置文件，使用默认配置")
        config = DEFAULT_CONFIG
        save_config(config)
    else:
        # 确保配置中包含所有必要的键
        if 'keywords' not in config:
            config['keywords'] = []
        if 'notified_entries' not in config:
            config['notified_entries'] = {}
        if 'telegram' not in config:
            config['telegram'] = {'bot_token': '', 'chat_id': ''}
        elif not isinstance(config['telegram'], dict):
            config['telegram'] = {'bot_token': '', 'chat_id': ''}
        else:
            if 'bot_token' not in config['telegram']:
                config['telegram']['bot_token'] = ''
            if 'chat_id' not in config['telegram']:
                config['telegram']['chat_id'] = ''
    
    return config

def save_config(config):
    """保存配置文件"""
    # 定义备份文件路径
    backup_file = CONFIG_FILE + '.bak'
    temp_file = CONFIG_FILE + '.tmp'
    
    try:
        # 检查配置对象大小，防止过大导致内存占用
        # 对历史记录进行清理，防止配置文件无限增长
        # 限制 notified_entries 记录数
        if 'notified_entries' in config and len(config['notified_entries']) > 50:
            # 按照时间排序，保留最新的50条
            sorted_entries = sorted(
                config['notified_entries'].items(),
                key=lambda item: item[1]['time'] if isinstance(item[1], dict) and 'time' in item[1] else '',
                reverse=True
            )[:50]
            config['notified_entries'] = dict(sorted_entries)
            logger.debug("配置保存前已限制通知记录为50条")
        
        # 限制 title_notifications 记录数
        if 'title_notifications' in config and len(config['title_notifications']) > 100:
            # 按照时间排序，保留最新的100条
            sorted_titles = sorted(
                config['title_notifications'].items(),
                key=lambda item: item[1]['time'] if isinstance(item[1], dict) and 'time' in item[1] else '',
                reverse=True
            )[:100]
            config['title_notifications'] = dict(sorted_titles)
            logger.debug("配置保存前已限制标题记录为100条")
        
        # 检查config对象是否有效且可序列化
        try:
            # 测试JSON序列化
            config_str = json.dumps(config, ensure_ascii=False)
            # 检查序列化后的配置文件大小，防止过大
            if len(config_str) > 1024 * 1024:  # 如果大于1MB
                logger.warning(f"配置文件过大 ({len(config_str)/1024:.2f} KB)，尝试清理")
                
                # 保留基本配置和历史通知记录，只清理非关键数据
                basic_config = {
                    'keywords': config.get('keywords', []),
                    'telegram': config.get('telegram', {'bot_token': '', 'chat_id': ''}),
                    'notified_entries': config.get('notified_entries', {}),  # 必须保留历史记录！
                }
                
                # 只保留notified_entries的最新20条，但绝不清空
                if 'notified_entries' in config and config['notified_entries']:
                    sorted_entries = sorted(
                        config['notified_entries'].items(),
                        key=lambda item: item[1]['time'] if isinstance(item[1], dict) and 'time' in item[1] else '',
                        reverse=True
                    )[:20]  # 只保留最新的20条
                    basic_config['notified_entries'] = dict(sorted_entries)
                
                # 彻底移除title_notifications等其他数据
                # basic_config中不包含title_notifications等，自动被清理
                
                # 使用清理后的配置
                config = basic_config
                config_str = json.dumps(config, ensure_ascii=False)
                logger.info(f"配置文件清理后大小: {len(config_str)/1024:.2f} KB，保留通知记录 {len(basic_config['notified_entries'])} 条")
        except (TypeError, ValueError) as e:
            logger.error(f"配置对象序列化失败: {e}")
            # 如果序列化失败，回退到默认配置
            config = DEFAULT_CONFIG
        
        # 先写入临时文件
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        
        # 如果原配置文件存在，先创建备份
        if os.path.exists(CONFIG_FILE):
            try:
                # 尝试复制原文件为备份
                import shutil
                shutil.copy2(CONFIG_FILE, backup_file)
            except Exception as e:
                logger.warning(f"创建配置文件备份失败: {e}")
        
        # 将临时文件重命名为正式配置文件
        os.replace(temp_file, CONFIG_FILE)
        
        # 执行垃圾回收
        gc.collect()
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        # 如果有备份，尝试从备份恢复
        if os.path.exists(backup_file):
            try:
                # 尝试从备份恢复
                import shutil
                shutil.copy2(backup_file, CONFIG_FILE)
                logger.info("已从备份恢复配置文件")
            except Exception as e2:
                logger.error(f"从备份恢复配置文件失败: {e2}")
    finally:
        # 清理可能残留的临时文件
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def send_telegram_message(message, config, reply_to_message_id=None):
    bot_token = config['telegram']['bot_token']
    chat_id = config['telegram']['chat_id']
    if not bot_token or not chat_id:
        logger.error("Telegram配置不完整")
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        response = requests.post(url, data=data)
        if response.status_code == 200:
            logger.info(f"Telegram消息发送成功")
            return True
        else:
            logger.error(f"Telegram消息发送失败: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram消息发送异常: {e}")
        return False

def check_rss_feed(config):
    """检查RSS源并匹配关键词"""
    # 确保config字典包含必要的键
    if 'keywords' not in config or not isinstance(config['keywords'], list):
        config['keywords'] = []
    if 'notified_entries' not in config or not isinstance(config['notified_entries'], dict):
        config['notified_entries'] = {}
    if not config['keywords']:
        logger.warning("没有设置关键词，跳过检查")
        return
    max_retries = 3
    retry_delay = 10
    config_changed = False
    for attempt in range(max_retries):
        try:
            logger.info("开始获取NodeSeek RSS源...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get("https://rss.nodeseek.com/", headers=headers, timeout=30)
            if response.status_code != 200:
                logger.error(f"获取RSS失败，HTTP状态码: {response.status_code}")
                if attempt < max_retries - 1:
                    current_retry_delay = retry_delay * (attempt + 1)
                    logger.info(f"将在{current_retry_delay}秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(current_retry_delay)
                    continue
                return
            logger.info("开始解析RSS内容...")
            feed = feedparser.parse(response.content)
            if not hasattr(feed, 'entries') or not feed.entries:
                logger.error("RSS解析失败或没有找到条目")
                if attempt < max_retries - 1:
                    current_retry_delay = retry_delay * (attempt + 1)
                    logger.info(f"将在{current_retry_delay}秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(current_retry_delay)
                    continue
                return
            logger.info(f"成功获取RSS，共找到 {len(feed.entries)} 条帖子")
            processed_count = 0
            for entry in feed.entries:
                try:
                    processed_count += 1
                    title = entry.title if hasattr(entry, 'title') else ''
                    link = entry.link if hasattr(entry, 'link') else ''
                    # 提取作者
                    author = ''
                    if hasattr(entry, 'author') and entry.author:
                        author = entry.author
                    elif hasattr(entry, 'author_detail') and entry.author_detail:
                        author = entry.author_detail.get('name', '')
                    elif hasattr(entry, 'dc_creator') and entry.dc_creator:
                        author = entry.dc_creator
                    elif hasattr(entry, 'summary') and entry.summary:
                        summary_match = re.search(r'作者[：:]\s*([^<\n\r]+)', entry.summary)
                        if summary_match:
                            author = summary_match.group(1).strip()
                    if not author and hasattr(entry, 'tags') and entry.tags:
                        for tag in entry.tags:
                            if hasattr(tag, 'term') and '作者' in tag.term:
                                author = tag.term.replace('作者:', '').replace('作者：', '').strip()
                                break
                    if not title or not link:
                        logger.warning("跳过缺少标题或链接的条目")
                        continue
                    title = re.sub(r'<[^>]+>', '', title).strip()
                    title = re.sub(r'\s+', ' ', title)
                    # 清理作者信息中的HTML标签和特殊字符
                    if author:
                        author = re.sub(r'<[^>]+>', '', author).strip()
                        author = re.sub(r'\s+', ' ', author)
                    else:
                        author = '未知'
                    
                    logger.debug(f"处理帖子: 标题='{title}', 作者='{author}', 链接={link}")
                    
                    # 优先从链接提取稳定的帖子ID，而不是依赖guid
                    post_id = None
                    post_id_patterns = [
                        r'/post-(\d+)',
                        r'/post/(\d+)', 
                        r'/topic/(\d+)',
                        r'/thread/(\d+)',
                        r'-(\d+)$'
                    ]
                    for pattern in post_id_patterns:
                        match = re.search(pattern, link)
                        if match:
                            post_id = match.group(1)
                            break
                    
                    # 如果链接中没找到ID，再尝试guid
                    if not post_id and hasattr(entry, 'guid') and entry.guid:
                        guid_str = str(entry.guid).strip()
                        # 从guid中提取数字
                        guid_match = re.search(r'(\d+)', guid_str)
                        if guid_match:
                            post_id = guid_match.group(1)
                    
                    # 增强作者名标准化处理
                    if author and author != '未知':
                        # 移除所有空白字符（包括中文空格、制表符等）
                        author_cleaned = re.sub(r'[\s\u3000\u00A0]+', '', author)
                        # 移除特殊符号和标点
                        author_cleaned = re.sub(r'[^\w\u4e00-\u9fff]', '', author_cleaned)
                        # 转为小写
                        author_normalized = author_cleaned.lower()
                    else:
                        author_normalized = 'unknown'
                    
                    logger.debug(f"作者名标准化: '{author}' -> '{author_normalized}'")
                    
                    # 生成唯一去重key：帖子ID_标准化作者名
                    if post_id:
                        unique_key = f"{post_id}_{author_normalized}"
                    else:
                        # 如果没有post_id，使用链接的hash作为ID
                        import hashlib
                        link_hash = hashlib.md5(link.encode()).hexdigest()[:8]
                        unique_key = f"{link_hash}_{author_normalized}"
                    
                    logger.info(f"生成unique_key: {unique_key} (post_id={post_id}, author='{author}' -> '{author_normalized}')")
                    
                    # 只用唯一key做去重
                    if unique_key in config['notified_entries']:
                        logger.info(f"✅ 跳过已通知过的帖子: {unique_key} 标题='{title}'")
                        continue
                    matched_keywords = []
                    for keyword in config['keywords']:
                        if keyword.lower() in title.lower():
                            matched_keywords.append(keyword)
                    if matched_keywords:
                        config['notified_entries'][unique_key] = {
                            'title': title,
                            'author': author,
                            'link': link,
                            'keywords': matched_keywords,
                            'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        }
                        config_changed = True
                        message = f"标题：{title}\n关键词：{', '.join(matched_keywords)}\n作者：{author}\n链接：{link}"
                        if send_telegram_message(message, config):
                            logger.info(f"检测到关键词 '{', '.join(matched_keywords)}' 在帖子 '{title}' (作者: {author}) 并成功发送通知")
                        else:
                            logger.error(f"发送通知失败，帖子标题: {title} (作者: {author})")
                            if unique_key in config['notified_entries']:
                                del config['notified_entries'][unique_key]
                except Exception as e:
                    logger.error(f"处理RSS条目时出错: {str(e)}")
                    continue
            # 限制notified_entries的数量为最新的50条
            if len(config['notified_entries']) > 50:
                sorted_entries = sorted(
                    config['notified_entries'].items(),
                    key=lambda item: item[1].get('time', '') if isinstance(item[1], dict) else '',
                    reverse=True
                )[:50]
                config['notified_entries'] = dict(sorted_entries)
                logger.info(f"已限制记录数量为50条")
                config_changed = True
            if config_changed:
                save_config(config)
            return
        except requests.exceptions.Timeout:
            logger.error(f"获取RSS超时 (尝试 {attempt+1}/{max_retries})")
        except requests.exceptions.ConnectionError:
            logger.error(f"连接RSS服务器失败 (尝试 {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"检查RSS时出错: {str(e)} (尝试 {attempt+1}/{max_retries})")
        if attempt < max_retries - 1:
            current_retry_delay = retry_delay * (attempt + 1)
            logger.info(f"将在{current_retry_delay}秒后重试 ({attempt+1}/{max_retries})")
            time.sleep(current_retry_delay)

def monitor_loop():
    logger.info("开始RSS监控")
    
    min_interval = int(os.environ.get('CHECK_MIN_INTERVAL', 30))
    max_interval = int(os.environ.get('CHECK_MAX_INTERVAL', 60))
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    detection_counter = 0
    max_detections = 20  # 最大检测次数，达到后重启程序

    try:
        while True:
            config = load_config()  # 每次检测前都重新加载配置
            try:
                check_rss_feed(config)
                consecutive_errors = 0
                detection_counter += 1
                logger.info(f"完成第 {detection_counter} 次RSS检测")
                
                # 检查是否达到重启阈值
                if detection_counter >= max_detections:
                    logger.info(f"已完成 {max_detections} 次RSS检测，程序即将重启以释放内存...")
                    # 清理PID文件
                    if os.path.exists(PID_FILE):
                        os.remove(PID_FILE)
                    # 重启程序
                    logger.info("正在重启程序...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                    
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"RSS监控异常: {e}")
                
                # 如果连续错误次数过多，增加检查间隔
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"连续出现{consecutive_errors}次错误，增加检查间隔")
                    long_wait = max_interval * 2
                    logger.info(f"等待{long_wait}秒后恢复检查...")
                    time.sleep(long_wait)
                    consecutive_errors = 0
                    continue
            
            # 生成随机等待时间
            check_interval = random.uniform(min_interval, max_interval)
            next_check_time = datetime.datetime.now() + datetime.timedelta(seconds=check_interval)
            logger.info(f"等待{check_interval:.2f}秒后进行下一次检查 (预计时间: {next_check_time.strftime('%H:%M:%S')})")
            time.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("监控被用户中断")
    except Exception as e:
        logger.error(f"监控循环严重异常: {e}")
    finally:
        # 清理PID文件
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

def telegram_command_listener():
    """监听Telegram消息，支持关键词管理指令"""
    config = load_config()
    bot_token = config['telegram']['bot_token']
    chat_id = config['telegram']['chat_id']
    if not bot_token or not chat_id:
        logger.error("Telegram配置不完整，无法启动指令监听")
        return
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
            params = {"timeout": 60, "offset": offset}
            resp = requests.get(url, params=params, timeout=65)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        message = update.get("message")
                        if not message:
                            continue
                        if str(message.get("chat", {}).get("id")) != str(chat_id):
                            continue  # 只响应指定chat_id
                        text = message.get("text", "").strip()
                        msg_id = message.get("message_id")
                        if text.startswith("/add "):
                            keyword = text[5:].strip()
                            if not keyword:
                                send_telegram_message("关键词不能为空", config, msg_id)
                                continue
                            # 不区分大小写且去除首尾空白判断是否已存在
                            if any(keyword.lower() == k.strip().lower() for k in config['keywords']):
                                send_telegram_message(f"关键词 '{keyword}' 已存在", config, msg_id)
                            else:
                                config['keywords'].append(keyword)
                                save_config(config)
                                send_telegram_message(f"关键词 '{keyword}' 已添加", config, msg_id)
                        elif text.startswith("/del "):
                            keyword = text[5:].strip()
                            if not keyword:
                                send_telegram_message("请输入要删除的关键词", config, msg_id)
                                continue
                            # 不区分大小写且去除首尾空白删除所有同名关键词
                            to_remove = [k for k in config['keywords'] if k.strip().lower() == keyword.lower()]
                            if to_remove:
                                for k in to_remove:
                                    config['keywords'].remove(k)
                                # 只保存keywords变化，不影响notified_entries
                                save_config(config)
                                send_telegram_message(f"关键词 '{keyword}' 已删除", config, msg_id)
                            else:
                                send_telegram_message(f"关键词 '{keyword}' 不存在", config, msg_id)
                        elif text.startswith("/list"):
                            if not config['keywords']:
                                send_telegram_message("当前没有设置任何关键词", config, msg_id)
                            else:
                                kw_list = '\n'.join([f"{i+1}. {k}" for i, k in enumerate(config['keywords'])])
                                send_telegram_message(f"当前关键词列表：\n{kw_list}", config, msg_id)
                        elif text.startswith("/help"):
                            help_msg = (
                                "NodeSeek 监控机器人指令：\n"
                                "/add 添加关键词\n"
                                "/del 删除关键词\n"
                                "/list 查看所有关键词\n"
                                "/help 查看帮助"
                            )
                            send_telegram_message(help_msg, config, msg_id)
            time.sleep(2)
        except Exception as e:
            logger.error(f"Telegram指令监听异常: {e}")
            time.sleep(5)

def init_config_from_env():
    """从环境变量初始化配置"""
    config = load_config()
    bot_token = os.environ.get('TG_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TG_CHAT_ID', '').strip()
    changed = False
    if bot_token and config['telegram']['bot_token'] != bot_token:
        config['telegram']['bot_token'] = bot_token
        changed = True
    if chat_id and config['telegram']['chat_id'] != chat_id:
        config['telegram']['chat_id'] = chat_id
        changed = True
    if changed:
        save_config(config)
    return config

if __name__ == "__main__":
    # 检查必要的库是否已安装
    missing_libraries = []
    try:
        import psutil
    except ImportError:
        missing_libraries.append("psutil")
    try:
        import feedparser
    except ImportError:
        missing_libraries.append("feedparser")
    if missing_libraries:
        print("检测到缺少以下库，请先安装:")
        for lib in missing_libraries:
            print(f"  - {lib}")
        print(f"pip install {' '.join(missing_libraries)}")
        sys.exit(1)

    # 初始化配置（从环境变量）
    config = init_config_from_env()
    if not config['telegram']['bot_token'] or not config['telegram']['chat_id']:
        logger.error("请设置TG_BOT_TOKEN和TG_CHAT_ID环境变量")
        print("请设置TG_BOT_TOKEN和TG_CHAT_ID环境变量")
        sys.exit(1)

    # 启动Telegram指令监听线程
    t = Thread(target=telegram_command_listener, daemon=True)
    t.start()

    # 启动监控主循环
    monitor_loop()