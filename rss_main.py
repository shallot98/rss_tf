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
            'notified_posts': [],
            'author_whitelist': [],
            'author_blacklist': [],
            'author_match_mode': 'contains'
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
            
            # Ensure all sources have author filter fields
            for source in config.get('rss_sources', []):
                if 'author_whitelist' not in source:
                    source['author_whitelist'] = []
                if 'author_blacklist' not in source:
                    source['author_blacklist'] = []
                if 'author_match_mode' not in source:
                    source['author_match_mode'] = 'contains'
        
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

def check_author_match(author, filter_list, match_mode='contains'):
    """
    检查作者是否匹配过滤列表
    
    Args:
        author: 作者名称
        filter_list: 过滤列表（可以是字符串列表或对象列表）
        match_mode: 匹配模式 ('exact' 或 'contains')
    
    Returns:
        tuple: (matched, author_obj) - 是否匹配和匹配的作者对象（如果有）
    """
    if not author or not filter_list:
        return False, None
    
    author_lower = author.lower().strip()
    
    for filter_item in filter_list:
        # Support both string and object format for backward compatibility
        if isinstance(filter_item, dict):
            filter_author = filter_item.get('name', '')
            item_match_mode = filter_item.get('match_mode', match_mode)
        else:
            filter_author = filter_item
            item_match_mode = match_mode
        
        filter_lower = filter_author.lower().strip()
        
        if item_match_mode == 'exact':
            if author_lower == filter_lower:
                return True, filter_item if isinstance(filter_item, dict) else None
        else:  # contains mode (default)
            if filter_lower in author_lower or author_lower in filter_lower:
                return True, filter_item if isinstance(filter_item, dict) else None
    
    return False, None

def check_author_keywords(title, author_obj):
    """
    检查内容是否匹配作者特定的关键词过滤
    
    Args:
        title: 文章标题
        author_obj: 作者对象（包含keywords和keywords_mode字段）
    
    Returns:
        tuple: (matches, matched_keywords) - 是否匹配和匹配的关键词列表
    """
    if not isinstance(author_obj, dict):
        # 如果不是字典对象，说明没有配置关键词过滤，默认通过
        return True, []
    
    keywords = author_obj.get('keywords', [])
    keywords_mode = author_obj.get('keywords_mode', 'none')
    
    # 'none' 模式或没有关键词：不进行关键词过滤
    if keywords_mode == 'none' or not keywords:
        return True, []
    
    # 检查关键词匹配
    matched_keywords = []
    title_lower = title.lower()
    
    for keyword in keywords:
        if keyword.lower() in title_lower:
            matched_keywords.append(keyword)
    
    # 根据模式判断是否通过
    if keywords_mode == 'all':
        # 全部关键词都必须匹配
        return len(matched_keywords) == len(keywords), matched_keywords
    elif keywords_mode == 'any':
        # 任一关键词匹配即可
        return len(matched_keywords) > 0, matched_keywords
    else:  # 'none' - 已在前面处理
        return True, []

def should_filter_by_author(author, title, source):
    """
    判断内容是否通过作者过滤（新版OR逻辑）
    
    Args:
        author: 作者名称
        title: 文章标题
        source: RSS源配置
    
    Returns:
        tuple: (passes, reason, matched_keywords) - 是否通过、原因、匹配的关键词
    """
    whitelist = source.get('author_whitelist', [])
    blacklist = source.get('author_blacklist', [])
    match_mode = source.get('author_match_mode', 'contains')
    
    # 黑名单检查（最高优先级）
    if blacklist:
        is_blacklisted, _ = check_author_match(author, blacklist, match_mode)
        if is_blacklisted:
            return False, f"作者 '{author}' 在黑名单中", []
    
    # 白名单检查
    if whitelist:
        if not author:
            # 如果没有作者信息且配置了白名单，不通过作者过滤
            return False, "作者为空且配置了白名单", []
        
        is_whitelisted, author_obj = check_author_match(author, whitelist, match_mode)
        if is_whitelisted:
            # 检查作者特定的关键词过滤
            matches_keywords, matched_kws = check_author_keywords(title, author_obj)
            if matches_keywords:
                return True, f"作者 '{author}' 在白名单中", matched_kws
            else:
                return False, f"作者 '{author}' 在白名单但内容不符合该作者的关键词过滤", []
        else:
            # 不在白名单中，不通过作者过滤
            return False, f"作者 '{author}' 不在白名单中", []
    
    # 没有配置白名单，不通过作者过滤（但不阻止，让关键词过滤来决定）
    return False, "未配置作者白名单", []

def check_rss_feed(source, config):
    """检查单个RSS源并匹配关键词或作者（使用改进的去重逻辑）"""
    source_name = source.get('name', 'Unknown')
    source_url = source.get('url', '')
    keywords = source.get('keywords', [])
    author_whitelist = source.get('author_whitelist', [])
    
    monitor_settings = config.get('monitor_settings', {})
    enable_debug = monitor_settings.get('enable_debug_logging', False)
    
    # 检查是否配置了关键词或作者过滤
    if not keywords and not author_whitelist:
        logger.info(f"源 '{source_name}' 没有设置关键词或作者白名单，跳过检查")
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
                    
                    # OR逻辑：检查关键词过滤 OR 作者过滤
                    # 任一条件满足即发送通知
                    
                    should_notify = False
                    notification_reason = ""
                    all_matched_keywords = []
                    
                    # 1. 检查全局关键词匹配
                    keyword_matched = False
                    keyword_matched_list = []
                    if keywords:
                        for keyword in keywords:
                            if keyword.lower() in title.lower():
                                keyword_matched_list.append(keyword)
                        
                        if keyword_matched_list:
                            keyword_matched = True
                    
                    # 2. 检查作者过滤
                    author_passes, author_reason, author_keywords = should_filter_by_author(author, title, source)
                    
                    # 3. 应用OR逻辑
                    if keyword_matched and author_passes:
                        # 两者都匹配
                        should_notify = True
                        notification_reason = "关键词+作者匹配"
                        all_matched_keywords = list(set(keyword_matched_list + author_keywords))
                    elif keyword_matched:
                        # 仅关键词匹配
                        should_notify = True
                        notification_reason = "关键词匹配"
                        all_matched_keywords = keyword_matched_list
                    elif author_passes:
                        # 仅作者匹配
                        should_notify = True
                        notification_reason = "作者匹配"
                        all_matched_keywords = author_keywords
                    
                    if should_notify:
                        # Prepare and send notification
                        keyword_display = ', '.join(all_matched_keywords) if all_matched_keywords else '(无)'
                        message = f"<b>来源：{source_name}</b>\n标题：{title}\n关键词：{keyword_display}\n作者：{author or '未知'}\n匹配原因：{notification_reason}\n链接：{link}"
                        
                        if send_telegram_message(message, config):
                            logger.info(f"[{source_name}] ✅ {notification_reason}，发送通知")
                            logger.info(f"[{source_name}]    标题: {title}")
                            if all_matched_keywords:
                                logger.info(f"[{source_name}]    关键词: {', '.join(all_matched_keywords)}")
                            if enable_debug:
                                logger.debug(f"[{source_name}]    Dedup key: {dedup_key}")
                            
                            # Mark as seen
                            dedup_hist.mark_seen(dedup_key, current_time)
                            sent_in_this_cycle.add(dedup_key)
                            newly_notified.append(dedup_key)
                            config_changed = True
                        else:
                            logger.error(f"[{source_name}] ❌ 发送通知失败，帖子标题: {title}")
                    else:
                        # 不满足任何条件，跳过
                        if enable_debug:
                            logger.debug(f"[{source_name}] ⏭️ 不满足过滤条件，跳过: {title}")
                            if not keyword_matched and keywords:
                                logger.debug(f"  关键词不匹配")
                            if not author_passes:
                                logger.debug(f"  作者过滤: {author_reason}")
                
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

def get_author_name(author_item):
    """从作者项获取名称（支持字符串和对象格式）"""
    if isinstance(author_item, dict):
        return author_item.get('name', '')
    return author_item

def normalize_author_list(author_list):
    """
    标准化作者列表格式
    将旧的字符串列表转换为新的对象列表格式
    """
    normalized = []
    for item in author_list:
        if isinstance(item, dict):
            # 已经是新格式
            if 'name' in item:
                normalized.append(item)
        else:
            # 旧格式，转换为新格式
            normalized.append({
                'name': item,
                'match_mode': 'exact',
                'keywords': [],
                'keywords_mode': 'none'
            })
    return normalized

def find_author_in_list(author_name, author_list):
    """在作者列表中查找作者（支持新旧格式）"""
    author_name_lower = author_name.lower().strip()
    for item in author_list:
        item_name = get_author_name(item).lower().strip()
        if item_name == author_name_lower:
            return item
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
                [{"text": "👤 作者管理", "callback_data": f"author_menu:{source['id']}"}],
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
                            [{"text": "👤 作者管理", "callback_data": f"author_menu:{source['id']}"}],
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
                    [{"text": "👤 作者管理", "callback_data": f"author_menu:{source['id']}"}],
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
        
        elif data.startswith("author_menu:"):
            source_id = data[12:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            answer_callback_query(query_id, config)
            
            whitelist = source.get('author_whitelist', [])
            blacklist = source.get('author_blacklist', [])
            match_mode = source.get('author_match_mode', 'contains')
            
            message_text = (
                f"<b>👤 作者过滤管理 - {source['name']}</b>\n\n"
                f"当前匹配模式: <b>{match_mode}</b>\n"
                f"白名单作者数: <b>{len(whitelist)}</b>\n"
                f"黑名单作者数: <b>{len(blacklist)}</b>\n\n"
                f"选择操作："
            )
            
            keyboard = [
                [{"text": "🤍 查看白名单", "callback_data": f"view_whitelist:{source_id}"}],
                [{"text": "🚫 查看黑名单", "callback_data": f"view_blacklist:{source_id}"}],
                [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                [{"text": f"🔄 切换匹配模式 (当前: {match_mode})", "callback_data": f"toggle_match_mode:{source_id}"}],
                [{"text": "🔙 返回源管理", "callback_data": f"source:{source_id}"}]
            ]
            
            edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("view_whitelist:"):
            source_id = data[15:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            answer_callback_query(query_id, config)
            
            whitelist = source.get('author_whitelist', [])
            
            if not whitelist:
                message_text = f"<b>🤍 白名单作者 - {source['name']}</b>\n\n(暂无白名单作者)"
                keyboard = [
                    [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                    [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                ]
            else:
                message_text = f"<b>🤍 白名单作者 - {source['name']}</b>\n\n点击作者查看详情：\n\n"
                keyboard = []
                
                for author in whitelist:
                    author_name = get_author_name(author)
                    display_name = author_name if len(author_name) <= 30 else author_name[:27] + "..."
                    
                    # 显示作者信息摘要
                    if isinstance(author, dict):
                        keywords = author.get('keywords', [])
                        kw_info = f" ({len(keywords)}个关键词)" if keywords else ""
                        message_text += f"• {author_name}{kw_info}\n"
                    else:
                        message_text += f"• {author_name}\n"
                    
                    keyboard.append([
                        {"text": f"📝 {display_name}", "callback_data": f"author_detail:{source_id}:{author_name}"}
                    ])
                
                keyboard.extend([
                    [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                    [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                ])
            
            edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("view_blacklist:"):
            source_id = data[15:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            answer_callback_query(query_id, config)
            
            blacklist = source.get('author_blacklist', [])
            
            if not blacklist:
                message_text = f"<b>🚫 黑名单作者 - {source['name']}</b>\n\n(暂无黑名单作者)"
                keyboard = [
                    [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                    [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                ]
            else:
                message_text = f"<b>🚫 黑名单作者 - {source['name']}</b>\n\n"
                keyboard = []
                
                for author in blacklist:
                    display_name = author if len(author) <= 30 else author[:27] + "..."
                    message_text += f"• {author}\n"
                    keyboard.append([
                        {"text": f"❌ {display_name}", "callback_data": f"del_blacklist:{source_id}:{author}"}
                    ])
                
                keyboard.extend([
                    [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                    [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                ])
            
            edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("add_whitelist:"):
            source_id = data[14:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            set_user_state(config, user_id, 'waiting_for_whitelist_author', {'source_id': source_id, 'message_id': message_id})
            answer_callback_query(query_id, config, "✏️ 请发送要添加的作者名称")
            
            msg_text = f"<b>➕ 添加白名单作者到 {source['name']}</b>\n\n请直接发送作者名称："
            edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=[
                [{"text": "❌ 取消", "callback_data": f"cancel_author_input:{source_id}"}]
            ])
        
        elif data.startswith("add_blacklist:"):
            source_id = data[14:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            set_user_state(config, user_id, 'waiting_for_blacklist_author', {'source_id': source_id, 'message_id': message_id})
            answer_callback_query(query_id, config, "✏️ 请发送要添加的作者名称")
            
            msg_text = f"<b>➕ 添加黑名单作者到 {source['name']}</b>\n\n请直接发送作者名称："
            edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=[
                [{"text": "❌ 取消", "callback_data": f"cancel_author_input:{source_id}"}]
            ])
        
        elif data.startswith("del_whitelist:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if source and 'author_whitelist' in source:
                    if author in source['author_whitelist']:
                        answer_callback_query(query_id, config)
                        
                        msg_text = f"<b>⚠️ 确认删除白名单作者</b>\n\n确定要从白名单中删除作者 <b>{author}</b> 吗？"
                        keyboard = [
                            [{"text": "✅ 确认删除", "callback_data": f"confirm_del_whitelist:{source_id}:{author}"}],
                            [{"text": "❌ 取消", "callback_data": f"view_whitelist:{source_id}"}]
                        ]
                        edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=keyboard)
                    else:
                        answer_callback_query(query_id, config, "❌ 作者不存在")
        
        elif data.startswith("confirm_del_whitelist:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if source and 'author_whitelist' in source:
                    if author in source['author_whitelist']:
                        source['author_whitelist'].remove(author)
                        save_config(config)
                        answer_callback_query(query_id, config, f"✓ 已删除白名单作者: {author}")
                        
                        whitelist = source.get('author_whitelist', [])
                        
                        if not whitelist:
                            message_text = f"<b>✓ 已删除白名单作者: {author}</b>\n\n<b>🤍 白名单作者 - {source['name']}</b>\n\n(暂无白名单作者)"
                            keyboard = [
                                [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                                [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                            ]
                        else:
                            message_text = f"<b>✓ 已删除白名单作者: {author}</b>\n\n<b>🤍 白名单作者 - {source['name']}</b>\n\n"
                            keyboard = []
                            
                            for a in whitelist:
                                display_name = a if len(a) <= 30 else a[:27] + "..."
                                message_text += f"• {a}\n"
                                keyboard.append([
                                    {"text": f"❌ {display_name}", "callback_data": f"del_whitelist:{source_id}:{a}"}
                                ])
                            
                            keyboard.extend([
                                [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                                [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                            ])
                        
                        edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("del_blacklist:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if source and 'author_blacklist' in source:
                    if author in source['author_blacklist']:
                        answer_callback_query(query_id, config)
                        
                        msg_text = f"<b>⚠️ 确认删除黑名单作者</b>\n\n确定要从黑名单中删除作者 <b>{author}</b> 吗？"
                        keyboard = [
                            [{"text": "✅ 确认删除", "callback_data": f"confirm_del_blacklist:{source_id}:{author}"}],
                            [{"text": "❌ 取消", "callback_data": f"view_blacklist:{source_id}"}]
                        ]
                        edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=keyboard)
                    else:
                        answer_callback_query(query_id, config, "❌ 作者不存在")
        
        elif data.startswith("confirm_del_blacklist:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if source and 'author_blacklist' in source:
                    if author in source['author_blacklist']:
                        source['author_blacklist'].remove(author)
                        save_config(config)
                        answer_callback_query(query_id, config, f"✓ 已删除黑名单作者: {author}")
                        
                        blacklist = source.get('author_blacklist', [])
                        
                        if not blacklist:
                            message_text = f"<b>✓ 已删除黑名单作者: {author}</b>\n\n<b>🚫 黑名单作者 - {source['name']}</b>\n\n(暂无黑名单作者)"
                            keyboard = [
                                [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                                [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                            ]
                        else:
                            message_text = f"<b>✓ 已删除黑名单作者: {author}</b>\n\n<b>🚫 黑名单作者 - {source['name']}</b>\n\n"
                            keyboard = []
                            
                            for a in blacklist:
                                display_name = a if len(a) <= 30 else a[:27] + "..."
                                message_text += f"• {a}\n"
                                keyboard.append([
                                    {"text": f"❌ {display_name}", "callback_data": f"del_blacklist:{source_id}:{a}"}
                                ])
                            
                            keyboard.extend([
                                [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                                [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                            ])
                        
                        edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("cancel_author_input:"):
            source_id = data[20:]
            clear_user_state(config, user_id)
            answer_callback_query(query_id, config, "已取消")
            
            source = get_source_by_id_or_name(config, source_id)
            if source:
                whitelist = source.get('author_whitelist', [])
                blacklist = source.get('author_blacklist', [])
                match_mode = source.get('author_match_mode', 'contains')
                
                message_text = (
                    f"<b>👤 作者过滤管理 - {source['name']}</b>\n\n"
                    f"当前匹配模式: <b>{match_mode}</b>\n"
                    f"白名单作者数: <b>{len(whitelist)}</b>\n"
                    f"黑名单作者数: <b>{len(blacklist)}</b>\n\n"
                    f"选择操作："
                )
                
                keyboard = [
                    [{"text": "🤍 查看白名单", "callback_data": f"view_whitelist:{source_id}"}],
                    [{"text": "🚫 查看黑名单", "callback_data": f"view_blacklist:{source_id}"}],
                    [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                    [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                    [{"text": f"🔄 切换匹配模式 (当前: {match_mode})", "callback_data": f"toggle_match_mode:{source_id}"}],
                    [{"text": "🔙 返回源管理", "callback_data": f"source:{source_id}"}]
                ]
                
                edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("toggle_match_mode:"):
            source_id = data[18:]
            source = get_source_by_id_or_name(config, source_id)
            
            if not source:
                answer_callback_query(query_id, config, "❌ 源不存在")
                return
            
            current_mode = source.get('author_match_mode', 'contains')
            new_mode = 'exact' if current_mode == 'contains' else 'contains'
            source['author_match_mode'] = new_mode
            save_config(config)
            
            answer_callback_query(query_id, config, f"✓ 已切换到 {new_mode} 模式")
            
            whitelist = source.get('author_whitelist', [])
            blacklist = source.get('author_blacklist', [])
            
            message_text = (
                f"<b>👤 作者过滤管理 - {source['name']}</b>\n\n"
                f"当前匹配模式: <b>{new_mode}</b>\n"
                f"白名单作者数: <b>{len(whitelist)}</b>\n"
                f"黑名单作者数: <b>{len(blacklist)}</b>\n\n"
                f"选择操作："
            )
            
            keyboard = [
                [{"text": "🤍 查看白名单", "callback_data": f"view_whitelist:{source_id}"}],
                [{"text": "🚫 查看黑名单", "callback_data": f"view_blacklist:{source_id}"}],
                [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                [{"text": f"🔄 切换匹配模式 (当前: {new_mode})", "callback_data": f"toggle_match_mode:{source_id}"}],
                [{"text": "🔙 返回源管理", "callback_data": f"source:{source_id}"}]
            ]
            
            edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("author_detail:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author_name = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if not source:
                    answer_callback_query(query_id, config, "❌ 源不存在")
                    return
                
                whitelist = source.get('author_whitelist', [])
                author_obj = find_author_in_list(author_name, whitelist)
                
                if not author_obj:
                    answer_callback_query(query_id, config, "❌ 作者不存在")
                    return
                
                answer_callback_query(query_id, config)
                
                # 显示作者详情
                if isinstance(author_obj, dict):
                    match_mode = author_obj.get('match_mode', 'exact')
                    keywords = author_obj.get('keywords', [])
                    keywords_mode = author_obj.get('keywords_mode', 'none')
                    
                    message_text = (
                        f"<b>📝 作者详情 - {source['name']}</b>\n\n"
                        f"作者: <b>{author_name}</b>\n"
                        f"匹配模式: <code>{match_mode}</code>\n"
                        f"关键词模式: <code>{keywords_mode}</code>\n\n"
                    )
                    
                    if keywords:
                        message_text += "<b>关键词过滤:</b>\n"
                        for kw in keywords:
                            message_text += f"  • {kw}\n"
                    else:
                        message_text += "<b>关键词过滤:</b> (无，推送所有内容)\n"
                else:
                    # 旧格式作者
                    message_text = (
                        f"<b>📝 作者详情 - {source['name']}</b>\n\n"
                        f"作者: <b>{author_name}</b>\n"
                        f"匹配模式: <code>exact</code> (旧格式)\n"
                        f"关键词过滤: (无，推送所有内容)\n"
                    )
                
                keyboard = [
                    [{"text": "📋 设置关键词", "callback_data": f"set_author_keywords:{source_id}:{author_name}"}],
                    [{"text": "🔄 切换关键词模式", "callback_data": f"toggle_keywords_mode:{source_id}:{author_name}"}],
                    [{"text": "🔄 切换匹配模式", "callback_data": f"toggle_author_match:{source_id}:{author_name}"}],
                    [{"text": "❌ 删除作者", "callback_data": f"del_whitelist:{source_id}:{author_name}"}],
                    [{"text": "🔙 返回白名单", "callback_data": f"view_whitelist:{source_id}"}]
                ]
                
                edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
        
        elif data.startswith("set_author_keywords:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author_name = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if not source:
                    answer_callback_query(query_id, config, "❌ 源不存在")
                    return
                
                set_user_state(config, user_id, 'waiting_for_author_keywords', {
                    'source_id': source_id,
                    'author_name': author_name,
                    'message_id': message_id
                })
                answer_callback_query(query_id, config, "✏️ 请发送关键词")
                
                msg_text = (
                    f"<b>📋 设置作者关键词过滤</b>\n\n"
                    f"作者: <b>{author_name}</b>\n\n"
                    f"请发送要为该作者设置的关键词，多个关键词用逗号分隔。\n"
                    f"例如: Python,JavaScript,Docker\n\n"
                    f"💡 留空表示不过滤关键词，推送该作者的所有内容"
                )
                edit_telegram_message(chat_id, message_id, msg_text, config, inline_keyboard=[
                    [{"text": "🗑️ 清空关键词", "callback_data": f"clear_author_keywords:{source_id}:{author_name}"}],
                    [{"text": "❌ 取消", "callback_data": f"author_detail:{source_id}:{author_name}"}]
                ])
        
        elif data.startswith("clear_author_keywords:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author_name = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if not source:
                    answer_callback_query(query_id, config, "❌ 源不存在")
                    return
                
                whitelist = source.get('author_whitelist', [])
                author_obj = find_author_in_list(author_name, whitelist)
                
                if author_obj:
                    if isinstance(author_obj, dict):
                        author_obj['keywords'] = []
                        author_obj['keywords_mode'] = 'none'
                        save_config(config)
                        answer_callback_query(query_id, config, "✓ 已清空关键词")
                    
                    # 返回作者详情页
                    if isinstance(author_obj, dict):
                        match_mode = author_obj.get('match_mode', 'exact')
                        keywords = author_obj.get('keywords', [])
                        keywords_mode = author_obj.get('keywords_mode', 'none')
                        
                        message_text = (
                            f"<b>✓ 已清空关键词</b>\n\n"
                            f"<b>📝 作者详情 - {source['name']}</b>\n\n"
                            f"作者: <b>{author_name}</b>\n"
                            f"匹配模式: <code>{match_mode}</code>\n"
                            f"关键词模式: <code>{keywords_mode}</code>\n\n"
                            f"<b>关键词过滤:</b> (无，推送所有内容)\n"
                        )
                    else:
                        message_text = (
                            f"<b>✓ 已清空关键词</b>\n\n"
                            f"<b>📝 作者详情 - {source['name']}</b>\n\n"
                            f"作者: <b>{author_name}</b>\n"
                            f"匹配模式: <code>exact</code> (旧格式)\n"
                            f"关键词过滤: (无，推送所有内容)\n"
                        )
                    
                    keyboard = [
                        [{"text": "📋 设置关键词", "callback_data": f"set_author_keywords:{source_id}:{author_name}"}],
                        [{"text": "🔄 切换关键词模式", "callback_data": f"toggle_keywords_mode:{source_id}:{author_name}"}],
                        [{"text": "🔄 切换匹配模式", "callback_data": f"toggle_author_match:{source_id}:{author_name}"}],
                        [{"text": "❌ 删除作者", "callback_data": f"del_whitelist:{source_id}:{author_name}"}],
                        [{"text": "🔙 返回白名单", "callback_data": f"view_whitelist:{source_id}"}]
                    ]
                    
                    edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
                else:
                    answer_callback_query(query_id, config, "❌ 作者不存在")
        
        elif data.startswith("toggle_keywords_mode:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author_name = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if not source:
                    answer_callback_query(query_id, config, "❌ 源不存在")
                    return
                
                whitelist = source.get('author_whitelist', [])
                author_obj = find_author_in_list(author_name, whitelist)
                
                if author_obj:
                    # 确保是新格式
                    if not isinstance(author_obj, dict):
                        # 转换为新格式
                        idx = whitelist.index(author_obj)
                        author_obj = {
                            'name': author_name,
                            'match_mode': 'exact',
                            'keywords': [],
                            'keywords_mode': 'none'
                        }
                        whitelist[idx] = author_obj
                    
                    # 切换模式: none -> any -> all -> none
                    current_mode = author_obj.get('keywords_mode', 'none')
                    if current_mode == 'none':
                        new_mode = 'any'
                    elif current_mode == 'any':
                        new_mode = 'all'
                    else:  # 'all'
                        new_mode = 'none'
                    
                    author_obj['keywords_mode'] = new_mode
                    save_config(config)
                    answer_callback_query(query_id, config, f"✓ 已切换到 {new_mode} 模式")
                    
                    # 返回作者详情页
                    match_mode = author_obj.get('match_mode', 'exact')
                    keywords = author_obj.get('keywords', [])
                    
                    message_text = (
                        f"<b>📝 作者详情 - {source['name']}</b>\n\n"
                        f"作者: <b>{author_name}</b>\n"
                        f"匹配模式: <code>{match_mode}</code>\n"
                        f"关键词模式: <code>{new_mode}</code>\n\n"
                    )
                    
                    if keywords:
                        message_text += "<b>关键词过滤:</b>\n"
                        for kw in keywords:
                            message_text += f"  • {kw}\n"
                        
                        if new_mode == 'all':
                            message_text += "\n💡 当前模式：必须匹配所有关键词\n"
                        elif new_mode == 'any':
                            message_text += "\n💡 当前模式：匹配任一关键词即可\n"
                    else:
                        message_text += "<b>关键词过滤:</b> (无，推送所有内容)\n"
                    
                    keyboard = [
                        [{"text": "📋 设置关键词", "callback_data": f"set_author_keywords:{source_id}:{author_name}"}],
                        [{"text": "🔄 切换关键词模式", "callback_data": f"toggle_keywords_mode:{source_id}:{author_name}"}],
                        [{"text": "🔄 切换匹配模式", "callback_data": f"toggle_author_match:{source_id}:{author_name}"}],
                        [{"text": "❌ 删除作者", "callback_data": f"del_whitelist:{source_id}:{author_name}"}],
                        [{"text": "🔙 返回白名单", "callback_data": f"view_whitelist:{source_id}"}]
                    ]
                    
                    edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
                else:
                    answer_callback_query(query_id, config, "❌ 作者不存在")
        
        elif data.startswith("toggle_author_match:"):
            parts = data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                author_name = parts[2]
                
                source = get_source_by_id_or_name(config, source_id)
                if not source:
                    answer_callback_query(query_id, config, "❌ 源不存在")
                    return
                
                whitelist = source.get('author_whitelist', [])
                author_obj = find_author_in_list(author_name, whitelist)
                
                if author_obj:
                    # 确保是新格式
                    if not isinstance(author_obj, dict):
                        # 转换为新格式
                        idx = whitelist.index(author_obj)
                        author_obj = {
                            'name': author_name,
                            'match_mode': 'exact',
                            'keywords': [],
                            'keywords_mode': 'none'
                        }
                        whitelist[idx] = author_obj
                    
                    # 切换匹配模式
                    current_mode = author_obj.get('match_mode', 'exact')
                    new_mode = 'contains' if current_mode == 'exact' else 'exact'
                    author_obj['match_mode'] = new_mode
                    save_config(config)
                    answer_callback_query(query_id, config, f"✓ 已切换到 {new_mode} 模式")
                    
                    # 返回作者详情页
                    keywords = author_obj.get('keywords', [])
                    keywords_mode = author_obj.get('keywords_mode', 'none')
                    
                    message_text = (
                        f"<b>📝 作者详情 - {source['name']}</b>\n\n"
                        f"作者: <b>{author_name}</b>\n"
                        f"匹配模式: <code>{new_mode}</code>\n"
                        f"关键词模式: <code>{keywords_mode}</code>\n\n"
                    )
                    
                    if keywords:
                        message_text += "<b>关键词过滤:</b>\n"
                        for kw in keywords:
                            message_text += f"  • {kw}\n"
                    else:
                        message_text += "<b>关键词过滤:</b> (无，推送所有内容)\n"
                    
                    keyboard = [
                        [{"text": "📋 设置关键词", "callback_data": f"set_author_keywords:{source_id}:{author_name}"}],
                        [{"text": "🔄 切换关键词模式", "callback_data": f"toggle_keywords_mode:{source_id}:{author_name}"}],
                        [{"text": "🔄 切换匹配模式", "callback_data": f"toggle_author_match:{source_id}:{author_name}"}],
                        [{"text": "❌ 删除作者", "callback_data": f"del_whitelist:{source_id}:{author_name}"}],
                        [{"text": "🔙 返回白名单", "callback_data": f"view_whitelist:{source_id}"}]
                    ]
                    
                    edit_telegram_message(chat_id, message_id, message_text, config, inline_keyboard=keyboard)
                else:
                    answer_callback_query(query_id, config, "❌ 作者不存在")
    
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
                                                [{"text": "👤 作者管理", "callback_data": f"author_menu:{source['id']}"}],
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
                                            'notified_posts': [],
                                            'author_whitelist': [],
                                            'author_blacklist': [],
                                            'author_match_mode': 'contains'
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
                                            [{"text": "👤 作者管理", "callback_data": f"author_menu:{source_id}"}],
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
                            
                            elif state == 'waiting_for_whitelist_author':
                                source_id = state_data.get('source_id')
                                source = get_source_by_id_or_name(config, source_id)
                                
                                if source:
                                    author = text.strip()
                                    if author:
                                        if 'author_whitelist' not in source:
                                            source['author_whitelist'] = []
                                        
                                        whitelist = source.get('author_whitelist', [])
                                        
                                        # 检查是否已存在（使用新的辅助函数）
                                        if find_author_in_list(author, whitelist):
                                            send_telegram_message(f"❌ 作者 '{author}' 已在白名单中\n\n请发送其他作者名称，或点击下方按钮取消：", config, msg_id, inline_keyboard=[
                                                [{"text": "❌ 取消", "callback_data": f"cancel_author_input:{source_id}"}]
                                            ])
                                        else:
                                            # 添加新格式的作者对象
                                            new_author = {
                                                'name': author,
                                                'match_mode': 'exact',
                                                'keywords': [],
                                                'keywords_mode': 'none'
                                            }
                                            source['author_whitelist'].append(new_author)
                                            save_config(config)
                                            clear_user_state(config, user_id)
                                            
                                            whitelist = source.get('author_whitelist', [])
                                            
                                            message_text = f"<b>✓ 已添加白名单作者: {author}</b>\n\n<b>🤍 白名单作者 - {source['name']}</b>\n\n点击作者查看详情：\n\n"
                                            keyboard = []
                                            
                                            for a in whitelist:
                                                author_name = get_author_name(a)
                                                display_name = author_name if len(author_name) <= 30 else author_name[:27] + "..."
                                                
                                                # 显示作者信息摘要
                                                if isinstance(a, dict):
                                                    keywords = a.get('keywords', [])
                                                    kw_info = f" ({len(keywords)}个关键词)" if keywords else ""
                                                    message_text += f"• {author_name}{kw_info}\n"
                                                else:
                                                    message_text += f"• {author_name}\n"
                                                
                                                keyboard.append([
                                                    {"text": f"📝 {display_name}", "callback_data": f"author_detail:{source_id}:{author_name}"}
                                                ])
                                            
                                            keyboard.extend([
                                                [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source_id}"}],
                                                [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                                            ])
                                            
                                            if original_msg_id:
                                                edit_telegram_message(chat_id, original_msg_id, message_text, config, inline_keyboard=keyboard)
                                            else:
                                                send_telegram_message(message_text, config, msg_id, inline_keyboard=keyboard)
                                    else:
                                        send_telegram_message("❌ 作者名称不能为空\n\n请发送要添加的作者名称：", config, msg_id, inline_keyboard=[
                                            [{"text": "❌ 取消", "callback_data": f"cancel_author_input:{source_id}"}]
                                        ])
                                else:
                                    clear_user_state(config, user_id)
                                    send_telegram_message("❌ 源不存在", config, msg_id)
                                continue
                            
                            elif state == 'waiting_for_blacklist_author':
                                source_id = state_data.get('source_id')
                                source = get_source_by_id_or_name(config, source_id)
                                
                                if source:
                                    author = text.strip()
                                    if author:
                                        if 'author_blacklist' not in source:
                                            source['author_blacklist'] = []
                                        
                                        if any(author.lower() == a.lower() for a in source.get('author_blacklist', [])):
                                            send_telegram_message(f"❌ 作者 '{author}' 已在黑名单中\n\n请发送其他作者名称，或点击下方按钮取消：", config, msg_id, inline_keyboard=[
                                                [{"text": "❌ 取消", "callback_data": f"cancel_author_input:{source_id}"}]
                                            ])
                                        else:
                                            source['author_blacklist'].append(author)
                                            save_config(config)
                                            clear_user_state(config, user_id)
                                            
                                            blacklist = source.get('author_blacklist', [])
                                            
                                            message_text = f"<b>✓ 已添加黑名单作者: {author}</b>\n\n<b>🚫 黑名单作者 - {source['name']}</b>\n\n"
                                            keyboard = []
                                            
                                            for a in blacklist:
                                                display_name = a if len(a) <= 30 else a[:27] + "..."
                                                message_text += f"• {a}\n"
                                                keyboard.append([
                                                    {"text": f"❌ {display_name}", "callback_data": f"del_blacklist:{source_id}:{a}"}
                                                ])
                                            
                                            keyboard.extend([
                                                [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source_id}"}],
                                                [{"text": "🔙 返回作者管理", "callback_data": f"author_menu:{source_id}"}]
                                            ])
                                            
                                            if original_msg_id:
                                                edit_telegram_message(chat_id, original_msg_id, message_text, config, inline_keyboard=keyboard)
                                            else:
                                                send_telegram_message(message_text, config, msg_id, inline_keyboard=keyboard)
                                    else:
                                        send_telegram_message("❌ 作者名称不能为空\n\n请发送要添加的作者名称：", config, msg_id, inline_keyboard=[
                                            [{"text": "❌ 取消", "callback_data": f"cancel_author_input:{source_id}"}]
                                        ])
                                else:
                                    clear_user_state(config, user_id)
                                    send_telegram_message("❌ 源不存在", config, msg_id)
                                continue
                            
                            elif state == 'waiting_for_author_keywords':
                                source_id = state_data.get('source_id')
                                author_name = state_data.get('author_name')
                                source = get_source_by_id_or_name(config, source_id)
                                
                                if source:
                                    keywords_text = text.strip()
                                    
                                    # 解析关键词（逗号分隔）
                                    if keywords_text:
                                        keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()]
                                    else:
                                        keywords = []
                                    
                                    # 查找作者
                                    whitelist = source.get('author_whitelist', [])
                                    author_obj = find_author_in_list(author_name, whitelist)
                                    
                                    if author_obj:
                                        # 确保是新格式
                                        if not isinstance(author_obj, dict):
                                            # 转换为新格式
                                            idx = whitelist.index(author_obj)
                                            author_obj = {
                                                'name': author_name,
                                                'match_mode': 'exact',
                                                'keywords': [],
                                                'keywords_mode': 'none'
                                            }
                                            whitelist[idx] = author_obj
                                        
                                        # 设置关键词
                                        author_obj['keywords'] = keywords
                                        if keywords:
                                            # 默认设置为 'any' 模式
                                            if author_obj.get('keywords_mode') == 'none':
                                                author_obj['keywords_mode'] = 'any'
                                        else:
                                            author_obj['keywords_mode'] = 'none'
                                        
                                        save_config(config)
                                        clear_user_state(config, user_id)
                                        
                                        # 显示作者详情
                                        match_mode = author_obj.get('match_mode', 'exact')
                                        keywords_mode = author_obj.get('keywords_mode', 'none')
                                        
                                        message_text = (
                                            f"<b>✓ 已设置关键词</b>\n\n"
                                            f"<b>📝 作者详情 - {source['name']}</b>\n\n"
                                            f"作者: <b>{author_name}</b>\n"
                                            f"匹配模式: <code>{match_mode}</code>\n"
                                            f"关键词模式: <code>{keywords_mode}</code>\n\n"
                                        )
                                        
                                        if keywords:
                                            message_text += "<b>关键词过滤:</b>\n"
                                            for kw in keywords:
                                                message_text += f"  • {kw}\n"
                                        else:
                                            message_text += "<b>关键词过滤:</b> (无，推送所有内容)\n"
                                        
                                        keyboard = [
                                            [{"text": "📋 设置关键词", "callback_data": f"set_author_keywords:{source_id}:{author_name}"}],
                                            [{"text": "🔄 切换关键词模式", "callback_data": f"toggle_keywords_mode:{source_id}:{author_name}"}],
                                            [{"text": "🔄 切换匹配模式", "callback_data": f"toggle_author_match:{source_id}:{author_name}"}],
                                            [{"text": "❌ 删除作者", "callback_data": f"del_whitelist:{source_id}:{author_name}"}],
                                            [{"text": "🔙 返回白名单", "callback_data": f"view_whitelist:{source_id}"}]
                                        ]
                                        
                                        if original_msg_id:
                                            edit_telegram_message(chat_id, original_msg_id, message_text, config, inline_keyboard=keyboard)
                                        else:
                                            send_telegram_message(message_text, config, msg_id, inline_keyboard=keyboard)
                                    else:
                                        clear_user_state(config, user_id)
                                        send_telegram_message("❌ 作者不存在", config, msg_id)
                                else:
                                    clear_user_state(config, user_id)
                                    send_telegram_message("❌ 源不存在", config, msg_id)
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
                                'notified_posts': [],
                                'author_whitelist': [],
                                'author_blacklist': [],
                                'author_match_mode': 'contains'
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
                        
                        elif text.startswith("/add_author "):
                            parts = text[12:].strip().split(None, 1)
                            if len(parts) < 2:
                                send_telegram_message("用法: /add_author <source_name> <author_name>", config, msg_id)
                                continue
                            
                            source_name, author = parts[0], parts[1]
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            if 'author_whitelist' not in source:
                                source['author_whitelist'] = []
                            
                            whitelist = source.get('author_whitelist', [])
                            
                            if find_author_in_list(author, whitelist):
                                send_telegram_message(f"作者 '{author}' 在源 '{source['name']}' 的白名单中已存在", config, msg_id)
                            else:
                                # 添加新格式的作者对象
                                new_author = {
                                    'name': author,
                                    'match_mode': 'exact',
                                    'keywords': [],
                                    'keywords_mode': 'none'
                                }
                                source['author_whitelist'].append(new_author)
                                save_config(config)
                                send_telegram_message(f"✓ 已为源 '{source['name']}' 添加白名单作者: {author}", config, msg_id)
                        
                        elif text.startswith("/del_author "):
                            parts = text[12:].strip().split(None, 1)
                            if len(parts) < 2:
                                send_telegram_message("用法: /del_author <source_name> <author_name>", config, msg_id)
                                continue
                            
                            source_name, author = parts[0], parts[1]
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            whitelist = source.get('author_whitelist', [])
                            author_obj = find_author_in_list(author, whitelist)
                            
                            if author_obj:
                                source['author_whitelist'].remove(author_obj)
                                save_config(config)
                                author_name = get_author_name(author_obj)
                                send_telegram_message(f"✓ 已从源 '{source['name']}' 删除白名单作者: {author_name}", config, msg_id)
                            else:
                                send_telegram_message(f"作者 '{author}' 在源 '{source['name']}' 的白名单中不存在", config, msg_id)
                        
                        elif text.startswith("/add_author_blacklist "):
                            parts = text[22:].strip().split(None, 1)
                            if len(parts) < 2:
                                send_telegram_message("用法: /add_author_blacklist <source_name> <author_name>", config, msg_id)
                                continue
                            
                            source_name, author = parts[0], parts[1]
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            if 'author_blacklist' not in source:
                                source['author_blacklist'] = []
                            
                            if any(author.lower() == a.lower() for a in source.get('author_blacklist', [])):
                                send_telegram_message(f"作者 '{author}' 在源 '{source['name']}' 的黑名单中已存在", config, msg_id)
                            else:
                                source['author_blacklist'].append(author)
                                save_config(config)
                                send_telegram_message(f"✓ 已为源 '{source['name']}' 添加黑名单作者: {author}", config, msg_id)
                        
                        elif text.startswith("/del_author_blacklist "):
                            parts = text[22:].strip().split(None, 1)
                            if len(parts) < 2:
                                send_telegram_message("用法: /del_author_blacklist <source_name> <author_name>", config, msg_id)
                                continue
                            
                            source_name, author = parts[0], parts[1]
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            blacklist = source.get('author_blacklist', [])
                            matching = [a for a in blacklist if a.lower() == author.lower()]
                            
                            if matching:
                                source['author_blacklist'].remove(matching[0])
                                save_config(config)
                                send_telegram_message(f"✓ 已从源 '{source['name']}' 删除黑名单作者: {matching[0]}", config, msg_id)
                            else:
                                send_telegram_message(f"作者 '{author}' 在源 '{source['name']}' 的黑名单中不存在", config, msg_id)
                        
                        elif text.startswith("/list_authors "):
                            source_name = text[14:].strip()
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            whitelist = source.get('author_whitelist', [])
                            blacklist = source.get('author_blacklist', [])
                            match_mode = source.get('author_match_mode', 'contains')
                            
                            lines = [f"<b>{source['name']}</b> 的作者过滤设置:\n"]
                            lines.append(f"全局匹配模式: <b>{match_mode}</b>\n")
                            
                            lines.append("<b>白名单作者:</b>")
                            if whitelist:
                                for i, a in enumerate(whitelist, 1):
                                    author_name = get_author_name(a)
                                    if isinstance(a, dict):
                                        a_match = a.get('match_mode', 'exact')
                                        keywords = a.get('keywords', [])
                                        kw_mode = a.get('keywords_mode', 'none')
                                        
                                        if keywords:
                                            kw_display = ', '.join(keywords[:3])
                                            if len(keywords) > 3:
                                                kw_display += f"... (共{len(keywords)}个)"
                                            lines.append(f"  {i}. {author_name}")
                                            lines.append(f"     模式: {a_match}, 关键词: {kw_display} ({kw_mode})")
                                        else:
                                            lines.append(f"  {i}. {author_name} (模式: {a_match}, 无关键词过滤)")
                                    else:
                                        lines.append(f"  {i}. {author_name}")
                            else:
                                lines.append("  (无)")
                            
                            lines.append("\n<b>黑名单作者:</b>")
                            if blacklist:
                                for i, a in enumerate(blacklist, 1):
                                    lines.append(f"  {i}. {a}")
                            else:
                                lines.append("  (无)")
                            
                            send_telegram_message('\n'.join(lines), config, msg_id)
                        
                        elif text.startswith("/manage_authors "):
                            source_name = text[16:].strip()
                            source = get_source_by_id_or_name(config, source_name)
                            
                            if not source:
                                send_telegram_message(f"源 '{source_name}' 不存在\n使用 /listsources 查看所有源", config, msg_id)
                                continue
                            
                            whitelist = source.get('author_whitelist', [])
                            blacklist = source.get('author_blacklist', [])
                            match_mode = source.get('author_match_mode', 'contains')
                            
                            message_text = (
                                f"<b>👤 作者过滤管理 - {source['name']}</b>\n\n"
                                f"当前匹配模式: <b>{match_mode}</b>\n"
                                f"白名单作者数: <b>{len(whitelist)}</b>\n"
                                f"黑名单作者数: <b>{len(blacklist)}</b>\n\n"
                                f"选择操作："
                            )
                            
                            keyboard = [
                                [{"text": "🤍 查看白名单", "callback_data": f"view_whitelist:{source['id']}"}],
                                [{"text": "🚫 查看黑名单", "callback_data": f"view_blacklist:{source['id']}"}],
                                [{"text": "➕ 添加白名单作者", "callback_data": f"add_whitelist:{source['id']}"}],
                                [{"text": "➕ 添加黑名单作者", "callback_data": f"add_blacklist:{source['id']}"}],
                                [{"text": f"🔄 切换匹配模式 (当前: {match_mode})", "callback_data": f"toggle_match_mode:{source['id']}"}],
                                [{"text": "🔙 返回源管理", "callback_data": f"source:{source['id']}"}]
                            ]
                            
                            send_telegram_message(message_text, config, msg_id, inline_keyboard=keyboard)
                        
                        elif text.startswith("/help") or text.startswith("/start"):
                            help_msg = (
                                "<b>🤖 RSS 监控机器人</b>\n\n"
                                "<b>📱 按钮式管理（推荐）：</b>\n"
                                "/manage 或 /listsources - 打开管理面板\n"
                                "• 使用按钮添加/删除RSS源\n"
                                "• 使用按钮添加/删除关键词\n"
                                "• 使用按钮管理作者过滤（白/黑名单）\n"
                                "• 为每个作者设置独立的关键词过滤\n"
                                "• 所有操作都可以通过按钮完成\n\n"
                                "<b>⚡ 过滤逻辑（OR模式）：</b>\n"
                                "满足以下任一条件即推送：\n"
                                "1️⃣ 匹配全局关键词白名单\n"
                                "2️⃣ 作者在白名单中（可配置该作者的专属关键词）\n"
                                "❌ 黑名单优先：作者或关键词在黑名单中将被排除\n\n"
                                "<b>⌨️ 命令行管理（备用）：</b>\n\n"
                                "<b>源管理:</b>\n"
                                "/addsource &lt;url&gt; &lt;name&gt; - 添加RSS源\n"
                                "/delsource &lt;序号或名称&gt; - 删除RSS源\n\n"
                                "<b>关键词管理:</b>\n"
                                "/add &lt;source_name&gt; &lt;keyword&gt; - 添加关键词\n"
                                "/del &lt;source_name&gt; &lt;序号或关键词&gt; - 删除关键词\n"
                                "/list &lt;source_name&gt; - 列出指定源的关键词\n"
                                "/list - 列出所有源的关键词\n\n"
                                "<b>作者过滤管理:</b>\n"
                                "/manage_authors &lt;source_name&gt; - 打开作者管理面板\n"
                                "/add_author &lt;source_name&gt; &lt;author&gt; - 添加白名单作者\n"
                                "/del_author &lt;source_name&gt; &lt;author&gt; - 删除白名单作者\n"
                                "/add_author_blacklist &lt;source_name&gt; &lt;author&gt; - 添加黑名单作者\n"
                                "/del_author_blacklist &lt;source_name&gt; &lt;author&gt; - 删除黑名单作者\n"
                                "/list_authors &lt;source_name&gt; - 查看作者过滤设置\n\n"
                                "<b>💡 使用建议：</b>\n"
                                "推荐使用 /manage 进入按钮管理界面，\n"
                                "所有添加和删除操作都更加直观方便！\n"
                                "点击作者名称可查看详情并设置专属关键词。\n\n"
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
