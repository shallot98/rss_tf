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

# Import deduplication module (after logger is configured)
try:
    from dedup import generate_dedup_key, DedupHistory, normalize_url
except ImportError as e:
    logger.error(f"Failed to import dedup module: {e}")
    print("ERROR: Failed to import dedup module. Make sure dedup.py is in the same directory.")
    sys.exit(1)

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
            'notified_posts': []
        }
    ],
    'monitor_settings': {
        'check_interval_min': 30,
        'check_interval_max': 60,
        'max_history': 100,
        'restart_after_checks': 100,
        'dedup_history_size': 1000,
        'dedup_debounce_hours': 24,
        'enable_debug_logging': False
    },
    'user_states': {}
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
            if 'user_states' not in config:
                config['user_states'] = {}
        
        return config

def save_config(config):
    """保存配置文件（原子写入，带fsync）"""
    with config_lock:
        backup_file = CONFIG_FILE + '.bak'
        temp_file = CONFIG_FILE + '.tmp'
        
        try:
            for source in config.get('rss_sources', []):
                max_history = config.get('monitor_settings', {}).get('max_history', 100)
                if len(source.get('notified_posts', [])) > max_history:
                    source['notified_posts'] = source['notified_posts'][-max_history:]
            
            # Write to temp file with fsync for durability
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                f.flush()
                # Ensure data is written to disk
                os.fsync(f.fileno())
            
            # Backup existing config before replacing
            if os.path.exists(CONFIG_FILE):
                try:
                    import shutil
                    shutil.copy2(CONFIG_FILE, backup_file)
                except Exception as e:
                    logger.warning(f"创建配置文件备份失败: {e}")
            
            # Atomic rename
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

def send_telegram_message(message, config, reply_to_message_id=None, inline_keyboard=None):
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
        if inline_keyboard:
            data["reply_markup"] = json.dumps({"inline_keyboard": inline_keyboard})
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

def edit_telegram_message(chat_id, message_id, message, config, inline_keyboard=None):
    """编辑Telegram消息"""
    bot_token = config['telegram']['bot_token']
    if not bot_token:
        logger.error("Telegram配置不完整")
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": message,
            "parse_mode": "HTML"
        }
        if inline_keyboard:
            data["reply_markup"] = json.dumps({"inline_keyboard": inline_keyboard})
        response = requests.post(url, data=data, timeout=30)
        if response.status_code == 200:
            logger.info("Telegram消息编辑成功")
            return True
        else:
            logger.error(f"Telegram消息编辑失败: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Telegram消息编辑异常: {e}")
        return False

def answer_callback_query(callback_query_id, config, text=None):
    """回应callback query"""
    bot_token = config['telegram']['bot_token']
    if not bot_token:
        logger.error("Telegram配置不完整")
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
        data = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        response = requests.post(url, data=data, timeout=30)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"回应callback query异常: {e}")
        return False

def load_dedup_history(source: dict, config: dict) -> DedupHistory:
    """
    Load deduplication history from source config.
    Migrates from old notified_posts format if needed.
    """
    monitor_settings = config.get('monitor_settings', {})
    max_size = monitor_settings.get('dedup_history_size', 1000)
    debounce_hours = monitor_settings.get('dedup_debounce_hours', 24)
    
    dedup_hist = DedupHistory(max_size=max_size, debounce_hours=debounce_hours)
    
    # Try to load from new format (dict with timestamps)
    if 'dedup_history' in source and isinstance(source['dedup_history'], dict):
        try:
            dedup_hist.from_dict(source['dedup_history'])
            logger.debug(f"Loaded {dedup_hist.size()} entries from dedup_history")
        except Exception as e:
            logger.warning(f"Failed to load dedup_history: {e}, starting fresh")
    
    # Migrate from old notified_posts format (list of keys without timestamps)
    elif 'notified_posts' in source and isinstance(source['notified_posts'], list):
        logger.info("Migrating from old notified_posts format to dedup_history")
        current_time = time.time()
        # Assume old entries were seen "now" to avoid re-sending
        migrated_history = {key: current_time for key in source['notified_posts'] if key}
        dedup_hist.from_dict(migrated_history, current_time)
        logger.info(f"Migrated {dedup_hist.size()} entries from notified_posts")
    
    return dedup_hist

def save_dedup_history(source: dict, dedup_hist: DedupHistory):
    """
    Save deduplication history to source config.
    Also maintains backward-compatible notified_posts for migration.
    """
    source['dedup_history'] = dedup_hist.to_dict()
    # Keep backward-compatible notified_posts list
    source['notified_posts'] = list(dedup_hist.history.keys())

def check_rss_feed(source, config):
    """检查单个RSS源并匹配关键词（使用改进的去重逻辑）"""
    source_name = source.get('name', 'Unknown')
    source_url = source.get('url', '')
    keywords = source.get('keywords', [])
    
    monitor_settings = config.get('monitor_settings', {})
    enable_debug = monitor_settings.get('enable_debug_logging', False)
    
    if not keywords:
        logger.info(f"源 '{source_name}' 没有设置关键词，跳过检查")
        return False
    
    if not source_url:
        logger.error(f"源 '{source_name}' 没有设置URL")
        return False
    
    # Load deduplication history
    dedup_hist = load_dedup_history(source, config)
    current_time = time.time()
    
    # Cleanup old entries before processing
    dedup_hist.cleanup_old_entries(current_time)
    
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
            
            # Track keys sent in this cycle to ensure single-send per item
            sent_in_this_cycle = set()
            newly_notified = []
            
            for entry in feed.entries:
                try:
                    # Extract basic fields
                    title = entry.title if hasattr(entry, 'title') else ''
                    link = entry.link if hasattr(entry, 'link') else ''
                    
                    # Extract author from various possible fields
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
                    
                    # Clean HTML from title and author
                    if title:
                        title = re.sub(r'<[^>]+>', '', title).strip()
                        title = re.sub(r'\s+', ' ', title)
                    
                    if author:
                        author = re.sub(r'<[^>]+>', '', author).strip()
                        author = re.sub(r'\s+', ' ', author)
                    
                    if not title or not link:
                        logger.warning(f"[{source_name}] 跳过缺少标题或链接的条目")
                        continue
                    
                    # Use new dedup key generation
                    dedup_key, debug_info = generate_dedup_key(entry)
                    
                    if not dedup_key:
                        logger.warning(f"[{source_name}] 无法生成dedup_key，跳过: title='{title}'")
                        continue
                    
                    # Debug logging
                    if enable_debug:
                        logger.debug(f"[{source_name}] Entry analysis:")
                        logger.debug(f"  Title: {title}")
                        logger.debug(f"  Link: {link}")
                        logger.debug(f"  Author: {author}")
                        logger.debug(f"  Dedup key: {dedup_key}")
                        logger.debug(f"  Key type: {debug_info.get('key_type')}")
                        if 'link_normalized' in debug_info:
                            logger.debug(f"  Normalized link: {debug_info['link_normalized']}")
                    
                    # Check for duplicates
                    is_dup, dup_reason = dedup_hist.is_duplicate(dedup_key, current_time)
                    
                    if is_dup:
                        logger.info(f"[{source_name}] ⏭️ 跳过重复项: {dedup_key} ({dup_reason})")
                        if enable_debug:
                            logger.debug(f"  Title was: {title}")
                        continue
                    
                    # Log if this is a re-send after debounce expiry
                    if dup_reason != 'new' and enable_debug:
                        logger.debug(f"[{source_name}] 🔄 去重窗口已过期，允许重新发送: {dup_reason}")
                    
                    # Check if already sent in this cycle (multi-keyword protection)
                    if dedup_key in sent_in_this_cycle:
                        logger.info(f"[{source_name}] ⏭️ 本轮已发送，跳过: {dedup_key}")
                        continue
                    
                    # Check keyword matches
                    matched_keywords = []
                    for keyword in keywords:
                        if keyword.lower() in title.lower():
                            matched_keywords.append(keyword)
                    
                    if matched_keywords:
                        # Prepare and send notification
                        message = f"<b>来源：{source_name}</b>\n标题：{title}\n关键词：{', '.join(matched_keywords)}\n作者：{author or '未知'}\n链接：{link}"
                        
                        if send_telegram_message(message, config):
                            logger.info(f"[{source_name}] ✅ 检测到关键词 '{', '.join(matched_keywords)}' 并发送通知")
                            logger.info(f"[{source_name}]    标题: {title}")
                            if enable_debug:
                                logger.debug(f"[{source_name}]    Dedup key: {dedup_key}")
                            
                            # Mark as seen
                            dedup_hist.mark_seen(dedup_key, current_time)
                            sent_in_this_cycle.add(dedup_key)
                            newly_notified.append(dedup_key)
                            config_changed = True
                        else:
                            logger.error(f"[{source_name}] ❌ 发送通知失败，帖子标题: {title}")
                
                except Exception as e:
                    logger.error(f"[{source_name}] 处理RSS条目时出错: {str(e)}")
                    if enable_debug:
                        import traceback
                        logger.debug(traceback.format_exc())
                    continue
            
            # Save updated history
            if config_changed and newly_notified:
                save_dedup_history(source, dedup_hist)
                save_config(config)
                logger.info(f"[{source_name}] 已保存 {len(newly_notified)} 个新通知记录")
                logger.info(f"[{source_name}] 去重历史大小: {dedup_hist.size()} 条")
            
            return True
            
        except requests.exceptions.Timeout:
            logger.error(f"[{source_name}] 获取RSS超时 (尝试 {attempt+1}/{max_retries})")
        except requests.exceptions.ConnectionError:
            logger.error(f"[{source_name}] 连接RSS服务器失败 (尝试 {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"[{source_name}] 检查RSS时出错: {str(e)} (尝试 {attempt+1}/{max_retries})")
            if enable_debug:
                import traceback
                logger.debug(traceback.format_exc())
        
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

def set_user_state(config, user_id, state, data=None):
    """设置用户状态"""
    if 'user_states' not in config:
        config['user_states'] = {}
    config['user_states'][str(user_id)] = {
        'state': state,
        'data': data or {},
        'timestamp': time.time()
    }
    save_config(config)

def get_user_state(config, user_id):
    """获取用户状态"""
    if 'user_states' not in config:
        return None
    return config['user_states'].get(str(user_id))

def clear_user_state(config, user_id):
    """清除用户状态"""
    if 'user_states' not in config:
        return
    if str(user_id) in config['user_states']:
        del config['user_states'][str(user_id)]
        save_config(config)

def handle_callback_query(callback_query, config):
    """处理内联键盘回调"""
    try:
        query_id = callback_query.get("id")
        data = callback_query.get("data", "")
        message = callback_query.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        from_user = callback_query.get("from", {})
        user_id = from_user.get("id")
        
        if data.startswith("source:"):
            source_id = data[7:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                edit_telegram_message(chat_id, message_id, "❌ 源不存在", config)
                return
            
            answer_callback_query(query_id, config)
            
            keywords = source.get('keywords', [])
            
            lines = [
                f"<b>📡 {source['name']}</b>",
                f"ID: <code>{source['id']}</code>",
                f"URL: {source['url']}",
                f"\n<b>关键词列表：</b>"
            ]
            
            if keywords:
                for i, kw in enumerate(keywords, 1):
                    lines.append(f"{i}. {kw}")
            else:
                lines.append("(暂无关键词)")
            
            keyboard = []
            
            if keywords:
                for i, kw in enumerate(keywords, 1):
                    keyboard.append([{
                        "text": f"❌ 删除: {kw}",
                        "callback_data": f"delkw:{source['id']}:{i-1}"
                    }])
            
            keyboard.extend([
                [{"text": "➕ 添加关键词", "callback_data": f"addkw:{source['id']}"}],
                [{"text": "🗑️ 删除此源", "callback_data": f"delsource_confirm:{source['id']}"}],
                [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
            ])
            
            edit_telegram_message(chat_id, message_id, '\n'.join(lines), config, inline_keyboard=keyboard)
        
        elif data == "back_to_sources":
            answer_callback_query(query_id, config)
            
            sources = config.get('rss_sources', [])
            keyboard = []
            
            for source in sources:
                kw_count = len(source.get('keywords', []))
                button_text = f"📡 {source['name']} ({kw_count}个关键词)"
                keyboard.append([{
                    "text": button_text,
                    "callback_data": f"source:{source['id']}"
                }])
            
            keyboard.append([{"text": "➕ 添加新RSS源", "callback_data": "addsource_start"}])
            
            message_text = "<b>📡 RSS源管理</b>\n\n点击下方按钮管理对应的RSS源："
            if not sources:
                message_text = "<b>📡 RSS源管理</b>\n\n当前没有RSS源，点击下方按钮添加："
            
            edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("delkw:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                kw_index = int(parts[2])
                
                source = get_source_by_id_or_name(config, source_id)
                if source and 'keywords' in source:
                    keywords = source['keywords']
                    if 0 <= kw_index < len(keywords):
                        deleted_kw = keywords.pop(kw_index)
                        save_config(config)
                        
                        answer_callback_query(query_id, config, f"✓ 已删除关键词: {deleted_kw}")
                        
                        keywords = source.get('keywords', [])
                        lines = [
                            f"<b>📡 {source['name']}</b>",
                            f"ID: <code>{source['id']}</code>",
                            f"URL: {source['url']}",
                            f"\n<b>关键词列表：</b>"
                        ]
                        
                        if keywords:
                            for i, kw in enumerate(keywords, 1):
                                lines.append(f"{i}. {kw}")
                        else:
                            lines.append("(暂无关键词)")
                        
                        keyboard = []
                        
                        if keywords:
                            for i, kw in enumerate(keywords, 1):
                                keyboard.append([{
                                    "text": f"❌ 删除: {kw}",
                                    "callback_data": f"delkw:{source['id']}:{i-1}"
                                }])
                        
                        keyboard.extend([
                            [{"text": "➕ 添加关键词", "callback_data": f"addkw:{source['id']}"}],
                            [{"text": "🗑️ 删除此源", "callback_data": f"delsource_confirm:{source['id']}"}],
                            [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
                        ])
                        
                        edit_telegram_message(chat_id, message_id, '\n'.join(lines), config, inline_keyboard=keyboard)
        
        elif data.startswith("addkw:"):
            source_id = data[6:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            set_user_state(config, user_id, 'waiting_for_keyword', {'source_id': source_id, 'message_id': message_id})
            answer_callback_query(query_id, config, "✏️ 请发送要添加的关键词")
            
            msg_text = f"<b>➕ 添加关键词到 {source['name']}</b>\n\n请直接发送要添加的关键词："
            edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=[
                [{"text": "❌ 取消", "callback_data": f"cancel_add:{source_id}"}]
            ])
        
        elif data.startswith("cancel_add:"):
            source_id = data[11:]
            clear_user_state(config, user_id)
            answer_callback_query(query_id, config, "已取消")
            
            source = get_source_by_id_or_name(config, source_id)
            if source:
                keywords = source.get('keywords', [])
                lines = [
                    f"<b>📡 {source['name']}</b>",
                    f"ID: <code>{source['id']}</code>",
                    f"URL: {source['url']}",
                    f"\n<b>关键词列表：</b>"
                ]
                
                if keywords:
                    for i, kw in enumerate(keywords, 1):
                        lines.append(f"{i}. {kw}")
                else:
                    lines.append("(暂无关键词)")
                
                keyboard = []
                
                if keywords:
                    for i, kw in enumerate(keywords, 1):
                        keyboard.append([{
                            "text": f"❌ 删除: {kw}",
                            "callback_data": f"delkw:{source['id']}:{i-1}"
                        }])
                
                keyboard.extend([
                    [{"text": "➕ 添加关键词", "callback_data": f"addkw:{source['id']}"}],
                    [{"text": "🗑️ 删除此源", "callback_data": f"delsource_confirm:{source['id']}"}],
                    [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
                ])
                
                edit_telegram_message(chat_id, message_id, '\n'.join(lines), config, inline_keyboard=keyboard)
        
        elif data.startswith("delsource_confirm:"):
            source_id = data[18:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            answer_callback_query(query_id, config)
            
            msg_text = f"<b>⚠️ 确认删除源</b>\n\n确定要删除 <b>{source['name']}</b> 吗？\n\n此操作将删除该源及其所有关键词，不可恢复！"
            keyboard = [
                [{"text": "✅ 确认删除", "callback_data": f"delsource:{source_id}"}],
                [{"text": "❌ 取消", "callback_data": f"source:{source_id}"}]
            ]
            edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("delsource:"):
            source_id = data[10:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            source_name = source['name']
            config['rss_sources'].remove(source)
            save_config(config)
            
            answer_callback_query(query_id, config, f"✓ 已删除源: {source_name}")
            
            sources = config.get('rss_sources', [])
            keyboard = []
            
            for source in sources:
                kw_count = len(source.get('keywords', []))
                button_text = f"📡 {source['name']} ({kw_count}个关键词)"
                keyboard.append([{
                    "text": button_text,
                    "callback_data": f"source:{source['id']}"
                }])
            
            keyboard.append([{"text": "➕ 添加新RSS源", "callback_data": "addsource_start"}])
            
            message_text = f"<b>✓ 已删除源: {source_name}</b>\n\n<b>📡 RSS源管理</b>\n\n点击下方按钮管理对应的RSS源："
            if not sources:
                message_text = f"<b>✓ 已删除源: {source_name}</b>\n\n<b>📡 RSS源管理</b>\n\n当前没有RSS源，点击下方按钮添加："
            
            edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data == "addsource_start":
            set_user_state(config, user_id, 'waiting_for_source_url', {'message_id': message_id})
            answer_callback_query(query_id, config, "✏️ 请发送RSS源的URL")
            
            msg_text = "<b>➕ 添加新RSS源</b>\n\n步骤 1/2：请发送RSS源的URL\n例如：https://rss.example.com/"
            edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=[
                [{"text": "❌ 取消", "callback_data": "cancel_addsource"}]
            ])
        
        elif data == "cancel_addsource":
            clear_user_state(config, user_id)
            answer_callback_query(query_id, config, "已取消")
            
            sources = config.get('rss_sources', [])
            keyboard = []
            
            for source in sources:
                kw_count = len(source.get('keywords', []))
                button_text = f"📡 {source['name']} ({kw_count}个关键词)"
                keyboard.append([{
                    "text": button_text,
                    "callback_data": f"source:{source['id']}"
                }])
            
            keyboard.append([{"text": "➕ 添加新RSS源", "callback_data": "addsource_start"}])
            
            message_text = "<b>📡 RSS源管理</b>\n\n点击下方按钮管理对应的RSS源："
            if not sources:
                message_text = "<b>📡 RSS源管理</b>\n\n当前没有RSS源，点击下方按钮添加："
            
            edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
    
    except Exception as e:
        logger.error(f"处理callback query时出错: {e}")
        import traceback
        logger.error(traceback.format_exc())

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
                        
                        callback_query = update.get("callback_query")
                        if callback_query:
                            handle_callback_query(callback_query, config)
                            continue
                        
                        message = update.get("message")
                        if not message:
                            continue
                        if str(message.get("chat", {}).get("id")) != str(chat_id):
                            continue
                        
                        text = message.get("text", "").strip()
                        msg_id = message.get("message_id")
                        from_user = message.get("from", {})
                        user_id = from_user.get("id")
                        
                        user_state = get_user_state(config, user_id)
                        
                        if user_state:
                            state = user_state.get('state')
                            state_data = user_state.get('data', {})
                            original_msg_id = state_data.get('message_id')
                            
                            if state == 'waiting_for_keyword':
                                source_id = state_data.get('source_id')
                                source = get_source_by_id_or_name(config, source_id)
                                
                                if source:
                                    keyword = text.strip()
                                    if keyword:
                                        if any(keyword.lower() == k.lower() for k in source.get('keywords', [])):
                                            send_telegram_message(f"❌ 关键词 '{keyword}' 已存在\n\n请发送其他关键词，或点击下方按钮取消：", config, msg_id, inline_keyboard=[
                                                [{"text": "❌ 取消", "callback_data": f"cancel_add:{source_id}"}]
                                            ])
                                        else:
                                            if 'keywords' not in source:
                                                source['keywords'] = []
                                            source['keywords'].append(keyword)
                                            save_config(config)
                                            clear_user_state(config, user_id)
                                            
                                            keywords = source.get('keywords', [])
                                            lines = [
                                                f"<b>✓ 已添加关键词: {keyword}</b>\n",
                                                f"<b>📡 {source['name']}</b>",
                                                f"ID: <code>{source['id']}</code>",
                                                f"URL: {source['url']}",
                                                f"\n<b>关键词列表：</b>"
                                            ]
                                            
                                            for i, kw in enumerate(keywords, 1):
                                                lines.append(f"{i}. {kw}")
                                            
                                            keyboard = []
                                            
                                            for i, kw in enumerate(keywords, 1):
                                                keyboard.append([{
                                                    "text": f"❌ 删除: {kw}",
                                                    "callback_data": f"delkw:{source['id']}:{i-1}"
                                                }])
                                            
                                            keyboard.extend([
                                                [{"text": "➕ 添加关键词", "callback_data": f"addkw:{source['id']}"}],
                                                [{"text": "🗑️ 删除此源", "callback_data": f"delsource_confirm:{source['id']}"}],
                                                [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
                                            ])
                                            
                                            if original_msg_id:
                                                edit_telegram_message(chat_id, original_msg_id, '\n'.join(lines), config, inline_keyboard=keyboard)
                                            else:
                                                send_telegram_message('\n'.join(lines), config, msg_id, inline_keyboard=keyboard)
                                    else:
                                        send_telegram_message("❌ 关键词不能为空\n\n请发送要添加的关键词：", config, msg_id, inline_keyboard=[
                                            [{"text": "❌ 取消", "callback_data": f"cancel_add:{source_id}"}]
                                        ])
                                else:
                                    clear_user_state(config, user_id)
                                    send_telegram_message("❌ 源不存在", config, msg_id)
                                continue
                            
                            elif state == 'waiting_for_source_url':
                                url = text.strip()
                                if url:
                                    if not url.startswith('http://') and not url.startswith('https://'):
                                        send_telegram_message("❌ URL格式不正确，必须以 http:// 或 https:// 开头\n\n请重新发送RSS源的URL：", config, msg_id, inline_keyboard=[
                                            [{"text": "❌ 取消", "callback_data": "cancel_addsource"}]
                                        ])
                                    else:
                                        state_data['url'] = url
                                        set_user_state(config, user_id, 'waiting_for_source_name', state_data)
                                        
                                        msg_text = f"<b>➕ 添加新RSS源</b>\n\nURL: {url}\n\n步骤 2/2：请发送RSS源的名称\n例如：NodeSeek"
                                        if original_msg_id:
                                            edit_telegram_message(chat_id, original_msg_id, msg_text, config, inline_keyboard=[
                                                [{"text": "❌ 取消", "callback_data": "cancel_addsource"}]
                                            ])
                                        else:
                                            send_telegram_message(msg_text, config, msg_id, inline_keyboard=[
                                                [{"text": "❌ 取消", "callback_data": "cancel_addsource"}]
                                            ])
                                else:
                                    send_telegram_message("❌ URL不能为空\n\n请发送RSS源的URL：", config, msg_id, inline_keyboard=[
                                        [{"text": "❌ 取消", "callback_data": "cancel_addsource"}]
                                    ])
                                continue
                            
                            elif state == 'waiting_for_source_name':
                                name = text.strip()
                                if name:
                                    source_id = name.lower().replace(' ', '_').replace('-', '_')
                                    source_id = re.sub(r'[^a-z0-9_]', '', source_id)
                                    
                                    if get_source_by_id_or_name(config, source_id) or get_source_by_id_or_name(config, name):
                                        send_telegram_message(f"❌ 源名称 '{name}' 已存在\n\n请发送其他名称：", config, msg_id, inline_keyboard=[
                                            [{"text": "❌ 取消", "callback_data": "cancel_addsource"}]
                                        ])
                                    else:
                                        url = state_data.get('url')
                                        new_source = {
                                            'id': source_id,
                                            'name': name,
                                            'url': url,
                                            'keywords': [],
                                            'notified_posts': []
                                        }
                                        config['rss_sources'].append(new_source)
                                        save_config(config)
                                        clear_user_state(config, user_id)
                                        
                                        lines = [
                                            f"<b>✓ 已添加RSS源</b>\n",
                                            f"<b>📡 {name}</b>",
                                            f"ID: <code>{source_id}</code>",
                                            f"URL: {url}",
                                            f"\n<b>关键词列表：</b>",
                                            "(暂无关键词)"
                                        ]
                                        
                                        keyboard = [
                                            [{"text": "➕ 添加关键词", "callback_data": f"addkw:{source_id}"}],
                                            [{"text": "🗑️ 删除此源", "callback_data": f"delsource_confirm:{source_id}"}],
                                            [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
                                        ]
                                        
                                        if original_msg_id:
                                            edit_telegram_message(chat_id, original_msg_id, '\n'.join(lines), config, inline_keyboard=keyboard)
                                        else:
                                            send_telegram_message('\n'.join(lines), config, msg_id, inline_keyboard=keyboard)
                                else:
                                    send_telegram_message("❌ 名称不能为空\n\n请发送RSS源的名称：", config, msg_id, inline_keyboard=[
                                        [{"text": "❌ 取消", "callback_data": "cancel_addsource"}]
                                    ])
                                continue
                        
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
                                'notified_posts': []
                            }
                            config['rss_sources'].append(new_source)
                            save_config(config)
                            send_telegram_message(f"✓ 已添加源: {name}\nURL: {url_part}\nID: {source_id}", config, msg_id)
                        
                        elif text.startswith("/delsource "):
                            identifier = text[11:].strip()
                            if not identifier:
                                send_telegram_message("用法: /delsource &lt;序号或名称&gt;", config, msg_id)
                                continue
                            
                            sources = config.get('rss_sources', [])
                            source_to_delete = None
                            
                            if identifier.isdigit():
                                idx = int(identifier)
                                if 1 <= idx <= len(sources):
                                    source_to_delete = sources[idx - 1]
                                else:
                                    send_telegram_message(f"✗ 序号 {idx} 无效，请使用 /listsources 查看", config, msg_id)
                                    continue
                            else:
                                source_to_delete = get_source_by_id_or_name(config, identifier)
                            
                            if not source_to_delete:
                                send_telegram_message(f"源 '{identifier}' 不存在", config, msg_id)
                                continue
                            
                            config['rss_sources'].remove(source_to_delete)
                            save_config(config)
                            send_telegram_message(f"✓ 已删除源: {source_to_delete['name']}", config, msg_id)
                        
                        elif text.startswith("/listsources") or text.startswith("/manage"):
                            sources = config.get('rss_sources', [])
                            keyboard = []
                            
                            for source in sources:
                                kw_count = len(source.get('keywords', []))
                                button_text = f"📡 {source['name']} ({kw_count}个关键词)"
                                keyboard.append([{
                                    "text": button_text,
                                    "callback_data": f"source:{source['id']}"
                                }])
                            
                            keyboard.append([{"text": "➕ 添加新RSS源", "callback_data": "addsource_start"}])
                            
                            message = "<b>📡 RSS源管理</b>\n\n点击下方按钮管理对应的RSS源："
                            if not sources:
                                message = "<b>📡 RSS源管理</b>\n\n当前没有RSS源，点击下方按钮添加："
                            
                            send_telegram_message(message, config, msg_id, inline_keyboard=keyboard)
                        
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
                                send_telegram_message("用法: /del &lt;source_name&gt; &lt;序号或关键词&gt;", config, msg_id)
                                continue
                            
                            source_name, keyword_identifier = parts[0], parts[1]
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            keywords = source.get('keywords', [])
                            keyword_to_remove = None
                            
                            if keyword_identifier.isdigit():
                                idx = int(keyword_identifier)
                                if 1 <= idx <= len(keywords):
                                    keyword_to_remove = keywords[idx - 1]
                                else:
                                    send_telegram_message(f"✗ 序号 {idx} 无效\n使用 /list {source['name']} 查看关键词列表", config, msg_id)
                                    continue
                            else:
                                matching = [k for k in keywords if k.lower() == keyword_identifier.lower()]
                                if matching:
                                    keyword_to_remove = matching[0]
                            
                            if keyword_to_remove:
                                source['keywords'].remove(keyword_to_remove)
                                save_config(config)
                                send_telegram_message(f"✓ 已从源 '{source['name']}' 删除关键词: {keyword_to_remove}", config, msg_id)
                            else:
                                send_telegram_message(f"关键词 '{keyword_identifier}' 在源 '{source['name']}' 中不存在", config, msg_id)
                        
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
                                kw_list = '\n'.join([f"<b>[{i+1}]</b> {k}" for i, k in enumerate(keywords)])
                                send_telegram_message(
                                    f"<b>{source['name']}</b> 的关键词列表:\n{kw_list}\n\n"
                                    f"💡 删除关键词可使用: /del {source['name']} &lt;序号或关键词&gt;",
                                    config, msg_id
                                )
                        
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
                        
                        elif text.startswith("/help") or text.startswith("/start"):
                            help_msg = (
                                "<b>🤖 RSS 监控机器人</b>\n\n"
                                "<b>📱 按钮式管理（推荐）：</b>\n"
                                "/manage 或 /listsources - 打开管理面板\n"
                                "• 使用按钮添加/删除RSS源\n"
                                "• 使用按钮添加/删除关键词\n"
                                "• 所有操作都可以通过按钮完成\n\n"
                                "<b>⌨️ 命令行管理（备用）：</b>\n\n"
                                "<b>源管理:</b>\n"
                                "/addsource &lt;url&gt; &lt;name&gt; - 添加RSS源\n"
                                "/delsource &lt;序号或名称&gt; - 删除RSS源\n\n"
                                "<b>关键词管理:</b>\n"
                                "/add &lt;source_name&gt; &lt;keyword&gt; - 添加关键词\n"
                                "/del &lt;source_name&gt; &lt;序号或关键词&gt; - 删除关键词\n"
                                "/list &lt;source_name&gt; - 列出指定源的关键词\n"
                                "/list - 列出所有源的关键词\n\n"
                                "<b>💡 使用建议：</b>\n"
                                "推荐使用 /manage 进入按钮管理界面，\n"
                                "所有添加和删除操作都更加直观方便！\n\n"
                                "/help - 查看此帮助"
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
