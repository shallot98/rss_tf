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
import gc
import psutil
from logging.handlers import RotatingFileHandler
from threading import Thread, Lock

try:
    import readline
except ImportError:
    pass

try:
    import resource
except ImportError:
    resource = None

# 配置文件和日志文件路径
if os.name == 'nt':
    DATA_DIR = os.path.join(os.getcwd(), 'data')
else:
    DATA_DIR = '/data'

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
LOG_FILE = os.path.join(DATA_DIR, 'monitor.log')
PID_FILE = os.path.join(DATA_DIR, 'monitor.pid')

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

# 配置文件锁
config_lock = Lock()

# 默认配置
DEFAULT_CONFIG = {
    'telegram': {
        'bot_token': '',
        'chat_id': ''
    },
    'rss_sources': [
        {
            'id': 'nodeseek',
            'name': 'NodeSeek',
            'url': 'https://rss.nodeseek.com/',
            'keywords': [],
            'notified_posts': [],
            'notified_authors': []
        }
    ],
    'monitor_settings': {
        'check_interval_min': 30,
        'check_interval_max': 60,
        'max_history': 100,
        'restart_after_checks': 100
    }
}

def load_config():
    """加载配置文件"""
    with config_lock:
        config = None
        backup_file = CONFIG_FILE + '.bak'
        
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
        
        if config is None and os.path.exists(backup_file):
            try:
                logger.info("主配置文件加载失败，尝试从备份文件加载")
                with open(backup_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info("从备份配置文件加载配置成功")
                save_config(config)
            except Exception as e:
                logger.error(f"从备份配置文件加载失败: {e}")
                config = None
        
        if config is None:
            logger.warning("无法加载配置文件，使用默认配置")
            config = DEFAULT_CONFIG.copy()
            save_config(config)
        else:
            if 'telegram' not in config:
                config['telegram'] = {'bot_token': '', 'chat_id': ''}
            if 'rss_sources' not in config:
                config['rss_sources'] = []
            if 'monitor_settings' not in config:
                config['monitor_settings'] = DEFAULT_CONFIG['monitor_settings'].copy()
        
        return config

def save_config(config):
    """保存配置文件"""
    with config_lock:
        backup_file = CONFIG_FILE + '.bak'
        temp_file = CONFIG_FILE + '.tmp'
        
        try:
            for source in config.get('rss_sources', []):
                max_history = config.get('monitor_settings', {}).get('max_history', 100)
                if len(source.get('notified_posts', [])) > max_history:
                    source['notified_posts'] = source['notified_posts'][-max_history:]
                if len(source.get('notified_authors', [])) > max_history:
                    source['notified_authors'] = source['notified_authors'][-max_history:]
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            if os.path.exists(CONFIG_FILE):
                try:
                    import shutil
                    shutil.copy2(CONFIG_FILE, backup_file)
                except Exception as e:
                    logger.warning(f"创建配置文件备份失败: {e}")
            
            os.replace(temp_file, CONFIG_FILE)
            gc.collect()
            
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            if os.path.exists(backup_file):
                try:
                    import shutil
                    shutil.copy2(backup_file, CONFIG_FILE)
                    logger.info("已从备份恢复配置文件")
                except Exception as e2:
                    logger.error(f"从备份恢复配置文件失败: {e2}")
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

def send_telegram_message(message, config, reply_to_message_id=None):
    """发送Telegram消息"""
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
        response = requests.post(url, data=data, timeout=30)
        if response.status_code == 200:
            logger.info("Telegram消息发送成功")
            return True
        else:
            logger.error(f"Telegram消息发送失败: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram消息发送异常: {e}")
        return False

def check_rss_feed(source, config):
    """检查单个RSS源并匹配关键词"""
    source_name = source.get('name', 'Unknown')
    source_url = source.get('url', '')
    keywords = source.get('keywords', [])
    
    if not keywords:
        logger.info(f"源 '{source_name}' 没有设置关键词，跳过检查")
        return False
    
    if not source_url:
        logger.error(f"源 '{source_name}' 没有设置URL")
        return False
    
    max_retries = 3
    retry_delay = 10
    config_changed = False
    
    for attempt in range(max_retries):
        try:
            logger.info(f"开始获取 RSS 源 '{source_name}' ({source_url})...")
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(source_url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"获取RSS失败，HTTP状态码: {response.status_code}")
                if attempt < max_retries - 1:
                    current_retry_delay = retry_delay * (attempt + 1)
                    logger.info(f"将在{current_retry_delay}秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(current_retry_delay)
                    continue
                return False
            
            logger.info(f"开始解析 RSS 源 '{source_name}' 内容...")
            feed = feedparser.parse(response.content)
            
            if not hasattr(feed, 'entries') or not feed.entries:
                logger.error(f"RSS 源 '{source_name}' 解析失败或没有找到条目")
                if attempt < max_retries - 1:
                    current_retry_delay = retry_delay * (attempt + 1)
                    logger.info(f"将在{current_retry_delay}秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(current_retry_delay)
                    continue
                return False
            
            logger.info(f"成功获取 RSS 源 '{source_name}'，共找到 {len(feed.entries)} 条帖子")
            
            notified_posts = set(source.get('notified_posts', []))
            notified_authors = set(source.get('notified_authors', []))
            
            for entry in feed.entries:
                try:
                    title = entry.title if hasattr(entry, 'title') else ''
                    link = entry.link if hasattr(entry, 'link') else ''
                    
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
                    
                    if author:
                        author = re.sub(r'<[^>]+>', '', author).strip()
                        author = re.sub(r'\s+', ' ', author)
                    else:
                        author = '未知'
                    
                    logger.debug(f"[{source_name}] 处理帖子: 标题='{title}', 作者='{author}', 链接={link}")
                    
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
                    
                    if not post_id and hasattr(entry, 'guid') and entry.guid:
                        guid_str = str(entry.guid).strip()
                        guid_match = re.search(r'(\d+)', guid_str)
                        if guid_match:
                            post_id = guid_match.group(1)
                    
                    if author and author != '未知':
                        author_cleaned = re.sub(r'[\s\u3000\u00A0]+', '', author)
                        author_cleaned = re.sub(r'[^\w\u4e00-\u9fff]', '', author_cleaned)
                        author_normalized = author_cleaned.lower()
                    else:
                        author_normalized = 'unknown'
                    
                    logger.debug(f"[{source_name}] 作者名标准化: '{author}' -> '{author_normalized}'")
                    
                    if post_id:
                        unique_key = f"{post_id}_{author_normalized}"
                    else:
                        import hashlib
                        link_hash = hashlib.md5(link.encode()).hexdigest()[:8]
                        unique_key = f"{link_hash}_{author_normalized}"
                    
                    logger.info(f"[{source_name}] 生成unique_key: {unique_key}")
                    
                    if unique_key in notified_posts:
                        logger.info(f"[{source_name}] ✅ 跳过已通知过的帖子: {unique_key}")
                        continue
                    
                    matched_keywords = []
                    for keyword in keywords:
                        if keyword.lower() in title.lower():
                            matched_keywords.append(keyword)
                    
                    if matched_keywords:
                        notified_posts.add(unique_key)
                        config_changed = True
                        
                        message = f"<b>来源：{source_name}</b>\n标题：{title}\n关键词：{', '.join(matched_keywords)}\n作者：{author}\n链接：{link}"
                        
                        if send_telegram_message(message, config):
                            logger.info(f"[{source_name}] 检测到关键词 '{', '.join(matched_keywords)}' 在帖子 '{title}' 并成功发送通知")
                        else:
                            logger.error(f"[{source_name}] 发送通知失败，帖子标题: {title}")
                            notified_posts.discard(unique_key)
                            config_changed = False
                
                except Exception as e:
                    logger.error(f"[{source_name}] 处理RSS条目时出错: {str(e)}")
                    continue
            
            if config_changed:
                max_history = config.get('monitor_settings', {}).get('max_history', 100)
                source['notified_posts'] = list(notified_posts)[-max_history:]
                source['notified_authors'] = list(notified_authors)[-max_history:]
                save_config(config)
            
            return True
            
        except requests.exceptions.Timeout:
            logger.error(f"[{source_name}] 获取RSS超时 (尝试 {attempt+1}/{max_retries})")
        except requests.exceptions.ConnectionError:
            logger.error(f"[{source_name}] 连接RSS服务器失败 (尝试 {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"[{source_name}] 检查RSS时出错: {str(e)} (尝试 {attempt+1}/{max_retries})")
        
        if attempt < max_retries - 1:
            current_retry_delay = retry_delay * (attempt + 1)
            logger.info(f"[{source_name}] 将在{current_retry_delay}秒后重试 ({attempt+1}/{max_retries})")
            time.sleep(current_retry_delay)
    
    return False

def monitor_loop():
    """监控主循环"""
    logger.info("开始RSS监控")
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    detection_counter = 0

    try:
        while True:
            config = load_config()
            monitor_settings = config.get('monitor_settings', {})
            min_interval = monitor_settings.get('check_interval_min', 30)
            max_interval = monitor_settings.get('check_interval_max', 60)
            max_detections = monitor_settings.get('restart_after_checks', 100)
            
            rss_sources = config.get('rss_sources', [])
            
            if not rss_sources:
                logger.warning("没有配置RSS源，等待配置...")
                time.sleep(60)
                continue
            
            try:
                for source in rss_sources:
                    source_name = source.get('name', 'Unknown')
                    logger.info(f"开始检查RSS源: {source_name}")
                    check_rss_feed(source, config)
                
                consecutive_errors = 0
                detection_counter += 1
                logger.info(f"完成第 {detection_counter} 次RSS检测")
                
                if detection_counter >= max_detections:
                    logger.info(f"已完成 {max_detections} 次RSS检测，程序即将重启以释放内存...")
                    if os.path.exists(PID_FILE):
                        os.remove(PID_FILE)
                    logger.info("正在重启程序...")
                    os.execv(sys.executable, [sys.executable] + sys.argv)
                    
            except Exception as e:
                consecutive_errors += 1
                logger.error(f"RSS监控异常: {e}")
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.warning(f"连续出现{consecutive_errors}次错误，增加检查间隔")
                    long_wait = max_interval * 2
                    logger.info(f"等待{long_wait}秒后恢复检查...")
                    time.sleep(long_wait)
                    consecutive_errors = 0
                    continue
            
            check_interval = random.uniform(min_interval, max_interval)
            next_check_time = datetime.datetime.now() + datetime.timedelta(seconds=check_interval)
            logger.info(f"等待{check_interval:.2f}秒后进行下一次检查 (预计时间: {next_check_time.strftime('%H:%M:%S')})")
            time.sleep(check_interval)
            
    except KeyboardInterrupt:
        logger.info("监控被用户中断")
    except Exception as e:
        logger.error(f"监控循环严重异常: {e}")
    finally:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

def get_source_by_id_or_name(config, identifier):
    """通过ID或名称获取RSS源"""
    for source in config.get('rss_sources', []):
        if source.get('id') == identifier or source.get('name') == identifier:
            return source
    return None

def telegram_command_listener():
    """监听Telegram消息，支持源和关键词管理指令"""
    config = load_config()
    bot_token = config['telegram']['bot_token']
    chat_id = config['telegram']['chat_id']
    
    if not bot_token or not chat_id:
        logger.error("Telegram配置不完整，无法启动指令监听")
        return
    
    offset = 0
    
    while True:
        try:
            config = load_config()
            bot_token = config['telegram']['bot_token']
            chat_id = config['telegram']['chat_id']
            
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
                            continue
                        
                        text = message.get("text", "").strip()
                        msg_id = message.get("message_id")
                        
                        if text.startswith("/addsource "):
                            parts = text[11:].strip().split(None, 1)
                            if len(parts) < 2:
                                send_telegram_message("用法: /addsource <url> <name>", config, msg_id)
                                continue
                            
                            url_part, name = parts[0], parts[1]
                            source_id = name.lower().replace(' ', '_')
                            
                            if get_source_by_id_or_name(config, source_id):
                                send_telegram_message(f"源 '{name}' 已存在", config, msg_id)
                                continue
                            
                            new_source = {
                                'id': source_id,
                                'name': name,
                                'url': url_part,
                                'keywords': [],
                                'notified_posts': [],
                                'notified_authors': []
                            }
                            config['rss_sources'].append(new_source)
                            save_config(config)
                            send_telegram_message(f"✓ 已添加源: {name}\nURL: {url_part}\nID: {source_id}", config, msg_id)
                        
                        elif text.startswith("/delsource "):
                            name = text[11:].strip()
                            if not name:
                                send_telegram_message("用法: /delsource <name>", config, msg_id)
                                continue
                            
                            source = get_source_by_id_or_name(config, name)
                            if not source:
                                send_telegram_message(f"源 '{name}' 不存在", config, msg_id)
                                continue
                            
                            config['rss_sources'].remove(source)
                            save_config(config)
                            send_telegram_message(f"✓ 已删除源: {source['name']}", config, msg_id)
                        
                        elif text.startswith("/listsources"):
                            sources = config.get('rss_sources', [])
                            if not sources:
                                send_telegram_message("当前没有配置任何RSS源", config, msg_id)
                            else:
                                lines = ["<b>RSS源列表:</b>"]
                                for i, source in enumerate(sources, 1):
                                    kw_count = len(source.get('keywords', []))
                                    lines.append(f"{i}. <b>{source['name']}</b> (ID: {source['id']})")
                                    lines.append(f"   URL: {source['url']}")
                                    lines.append(f"   关键词: {kw_count}个")
                                send_telegram_message('\n'.join(lines), config, msg_id)
                        
                        elif text.startswith("/add "):
                            parts = text[5:].strip().split(None, 1)
                            if len(parts) < 2:
                                send_telegram_message("用法: /add <source_name> <keyword>", config, msg_id)
                                continue
                            
                            source_name, keyword = parts[0], parts[1]
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            if any(keyword.lower() == k.lower() for k in source.get('keywords', [])):
                                send_telegram_message(f"关键词 '{keyword}' 在源 '{source['name']}' 中已存在", config, msg_id)
                            else:
                                if 'keywords' not in source:
                                    source['keywords'] = []
                                source['keywords'].append(keyword)
                                save_config(config)
                                send_telegram_message(f"✓ 已为源 '{source['name']}' 添加关键词: {keyword}", config, msg_id)
                        
                        elif text.startswith("/del "):
                            parts = text[5:].strip().split(None, 1)
                            if len(parts) < 2:
                                send_telegram_message("用法: /del <source_name> <keyword>", config, msg_id)
                                continue
                            
                            source_name, keyword = parts[0], parts[1]
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            keywords = source.get('keywords', [])
                            to_remove = [k for k in keywords if k.lower() == keyword.lower()]
                            
                            if to_remove:
                                for k in to_remove:
                                    source['keywords'].remove(k)
                                save_config(config)
                                send_telegram_message(f"✓ 已从源 '{source['name']}' 删除关键词: {keyword}", config, msg_id)
                            else:
                                send_telegram_message(f"关键词 '{keyword}' 在源 '{source['name']}' 中不存在", config, msg_id)
                        
                        elif text.startswith("/list "):
                            source_name = text[6:].strip()
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            keywords = source.get('keywords', [])
                            if not keywords:
                                send_telegram_message(f"源 '{source['name']}' 没有设置任何关键词", config, msg_id)
                            else:
                                kw_list = '\n'.join([f"{i+1}. {k}" for i, k in enumerate(keywords)])
                                send_telegram_message(f"<b>{source['name']}</b> 的关键词列表:\n{kw_list}", config, msg_id)
                        
                        elif text.startswith("/list"):
                            sources = config.get('rss_sources', [])
                            if not sources:
                                send_telegram_message("当前没有配置任何RSS源\n使用 /addsource 添加源", config, msg_id)
                            else:
                                lines = ["<b>所有源的关键词:</b>"]
                                for source in sources:
                                    keywords = source.get('keywords', [])
                                    lines.append(f"\n<b>{source['name']}</b>:")
                                    if keywords:
                                        for i, k in enumerate(keywords, 1):
                                            lines.append(f"  {i}. {k}")
                                    else:
                                        lines.append("  (无关键词)")
                                send_telegram_message('\n'.join(lines), config, msg_id)
                        
                        elif text.startswith("/help"):
                            help_msg = (
                                "<b>RSS 监控机器人指令:</b>\n\n"
                                "<b>源管理:</b>\n"
                                "/addsource &lt;url&gt; &lt;name&gt; - 添加RSS源\n"
                                "/delsource &lt;name&gt; - 删除RSS源\n"
                                "/listsources - 列出所有RSS源\n\n"
                                "<b>关键词管理:</b>\n"
                                "/add &lt;source_name&gt; &lt;keyword&gt; - 添加关键词\n"
                                "/del &lt;source_name&gt; &lt;keyword&gt; - 删除关键词\n"
                                "/list &lt;source_name&gt; - 列出指定源的关键词\n"
                                "/list - 列出所有源的关键词\n\n"
                                "/help - 查看帮助"
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

    config = init_config_from_env()
    if not config['telegram']['bot_token'] or not config['telegram']['chat_id']:
        logger.error("请设置TG_BOT_TOKEN和TG_CHAT_ID环境变量")
        print("请设置TG_BOT_TOKEN和TG_CHAT_ID环境变量")
        sys.exit(1)

    t = Thread(target=telegram_command_listener, daemon=True)
    t.start()

    monitor_loop()
