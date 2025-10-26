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
import hashlib
import html
from logging.handlers import RotatingFileHandler
from threading import Thread, Lock
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime

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
HTTP_CACHE_FILE = os.path.join(DATA_DIR, 'http_cache.json')

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
http_cache_lock = Lock()

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
        'restart_after_checks': 100,
        'max_concurrent_feeds': 5,
        'per_feed_min_interval': 60,
        'enable_media_links': False
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

def load_http_cache():
    """加载HTTP缓存"""
    with http_cache_lock:
        if os.path.exists(HTTP_CACHE_FILE):
            try:
                with open(HTTP_CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"加载HTTP缓存失败: {e}")
        return {}

def save_http_cache(cache):
    """保存HTTP缓存"""
    with http_cache_lock:
        temp_file = HTTP_CACHE_FILE + '.tmp'
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, HTTP_CACHE_FILE)
        except Exception as e:
            logger.error(f"保存HTTP缓存失败: {e}")
        finally:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

def extract_entry_id(entry, source_url):
    """提取条目ID，带fallback"""
    if hasattr(entry, 'id') and entry.id:
        return str(entry.id).strip()
    
    if hasattr(entry, 'guid') and entry.guid:
        return str(entry.guid).strip()
    
    if hasattr(entry, 'link') and entry.link:
        return entry.link.strip()
    
    fallback_parts = []
    if hasattr(entry, 'title') and entry.title:
        fallback_parts.append(str(entry.title))
    
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        try:
            dt = datetime.datetime(*entry.published_parsed[:6])
            fallback_parts.append(dt.isoformat())
        except Exception:
            pass
    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
        try:
            dt = datetime.datetime(*entry.updated_parsed[:6])
            fallback_parts.append(dt.isoformat())
        except Exception:
            pass
    
    if fallback_parts:
        fallback_str = '_'.join(fallback_parts)
    else:
        fallback_str = 'no_id_' + str(hash(str(entry)))
    
    return hashlib.sha1(fallback_str.encode('utf-8')).hexdigest()

def extract_entry_link(entry):
    """提取条目链接，优先使用rel='alternate'"""
    if hasattr(entry, 'links') and entry.links:
        for link in entry.links:
            if isinstance(link, dict) and link.get('rel') == 'alternate' and link.get('href'):
                return link['href'].strip()
    
    if hasattr(entry, 'link') and entry.link:
        return entry.link.strip()
    
    return ''

def extract_entry_title(entry):
    """提取条目标题"""
    if hasattr(entry, 'title') and entry.title:
        title = entry.title
        title = re.sub(r'<[^>]+>', '', title)
        title = html.unescape(title)
        title = re.sub(r'\s+', ' ', title).strip()
        return title
    return ''

def extract_entry_author(entry):
    """提取条目作者"""
    if hasattr(entry, 'author') and entry.author:
        author = entry.author
    elif hasattr(entry, 'author_detail') and hasattr(entry.author_detail, 'name') and entry.author_detail.name:
        author = entry.author_detail.name
    elif hasattr(entry, 'dc_creator') and entry.dc_creator:
        author = entry.dc_creator
    else:
        author = ''
    
    if author:
        author = re.sub(r'<[^>]+>', '', author)
        author = html.unescape(author)
        author = re.sub(r'\s+', ' ', author).strip()
    
    return author

def extract_entry_time(entry):
    """提取条目时间，返回ISO格式字符串或None"""
    time_struct = None
    
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        time_struct = entry.published_parsed
    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
        time_struct = entry.updated_parsed
    
    if time_struct:
        try:
            dt = datetime.datetime(*time_struct[:6])
            return dt.isoformat()
        except Exception:
            pass
    
    return None

def extract_entry_content(entry):
    """提取条目内容用于显示"""
    content = ''
    
    if hasattr(entry, 'content') and entry.content and len(entry.content) > 0:
        content = entry.content[0].get('value', '')
    elif hasattr(entry, 'summary') and entry.summary:
        content = entry.summary
    elif hasattr(entry, 'description') and entry.description:
        content = entry.description
    
    if content:
        content = re.sub(r'<[^>]+>', '', content)
        content = html.unescape(content)
        content = re.sub(r'\s+', ' ', content).strip()
    
    return content

def extract_entry_media(entry, enable_media_links):
    """提取条目中的媒体链接"""
    if not enable_media_links:
        return []
    
    media_links = []
    
    if hasattr(entry, 'enclosures') and entry.enclosures:
        for enc in entry.enclosures:
            if isinstance(enc, dict) and enc.get('href'):
                media_links.append(enc['href'])
    
    if hasattr(entry, 'media_content') and entry.media_content:
        for media in entry.media_content:
            if isinstance(media, dict) and media.get('url'):
                media_links.append(media['url'])
    
    return media_links

def generate_unique_key(entry_id, source_url, title, time_str):
    """生成唯一键用于去重"""
    try:
        parsed = urlparse(source_url)
        source_host = parsed.netloc or 'unknown'
    except Exception:
        source_host = 'unknown'
    
    if entry_id and not entry_id.startswith('sha1:'):
        return f"{source_host}:{entry_id}"
    
    fallback_str = f"{title}_{time_str or 'no_time'}"
    fallback_hash = hashlib.sha1(fallback_str.encode('utf-8')).hexdigest()
    return f"{source_host}:sha1:{fallback_hash}"

def truncate_for_telegram(text, max_length=4000):
    """截断文本以符合Telegram限制"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + '...'

def html_escape_for_telegram(text):
    """转义HTML特殊字符用于Telegram"""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text

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
    """检查单个RSS源并匹配关键词 - 通用RSS/Atom兼容"""
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
    base_retry_delay = 10
    config_changed = False
    http_cache = load_http_cache()
    cache_key = source_url
    enable_media_links = config.get('monitor_settings', {}).get('enable_media_links', False)
    
    for attempt in range(max_retries):
        try:
            logger.info(f"[{source_name}] 开始获取RSS源 ({source_url})...")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; RSS-TF-Monitor/1.0; +https://github.com/rss-monitor)',
                'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            cache_entry = http_cache.get(cache_key, {})
            if cache_entry.get('etag'):
                headers['If-None-Match'] = cache_entry['etag']
            if cache_entry.get('last_modified'):
                headers['If-Modified-Since'] = cache_entry['last_modified']
            
            response = requests.get(source_url, headers=headers, timeout=30)
            
            logger.info(f"[{source_name}] HTTP状态码: {response.status_code}")
            
            if response.status_code == 304:
                logger.info(f"[{source_name}] 内容未修改 (304)，跳过处理")
                return True
            
            if response.status_code == 429:
                retry_after = response.headers.get('Retry-After', str(base_retry_delay * 2))
                try:
                    wait_time = int(retry_after)
                except ValueError:
                    try:
                        retry_date = parsedate_to_datetime(retry_after)
                        wait_time = max(0, (retry_date - datetime.datetime.now(retry_date.tzinfo)).total_seconds())
                    except Exception:
                        wait_time = base_retry_delay * 2
                
                logger.warning(f"[{source_name}] 触发速率限制 (429)，等待 {wait_time}秒")
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                return False
            
            if response.status_code == 503:
                retry_after = response.headers.get('Retry-After')
                if retry_after:
                    try:
                        wait_time = int(retry_after)
                        logger.warning(f"[{source_name}] 服务不可用 (503)，Retry-After: {wait_time}秒")
                        if attempt < max_retries - 1 and wait_time < 300:
                            time.sleep(wait_time)
                            continue
                    except ValueError:
                        pass
                
                if attempt < max_retries - 1:
                    current_retry_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 5)
                    logger.info(f"[{source_name}] 等待 {current_retry_delay:.2f}秒后重试")
                    time.sleep(current_retry_delay)
                    continue
                return False
            
            if response.status_code != 200:
                logger.error(f"[{source_name}] 获取RSS失败，HTTP状态码: {response.status_code}")
                if attempt < max_retries - 1:
                    current_retry_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 5)
                    logger.info(f"[{source_name}] 将在{current_retry_delay:.2f}秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(current_retry_delay)
                    continue
                return False
            
            if 'etag' in response.headers:
                http_cache[cache_key] = http_cache.get(cache_key, {})
                http_cache[cache_key]['etag'] = response.headers['etag']
            
            if 'last-modified' in response.headers:
                http_cache[cache_key] = http_cache.get(cache_key, {})
                http_cache[cache_key]['last_modified'] = response.headers['last-modified']
            
            save_http_cache(http_cache)
            
            logger.info(f"[{source_name}] 开始解析RSS/Atom内容...")
            
            response.encoding = response.apparent_encoding or 'utf-8'
            feed = feedparser.parse(response.content)
            
            if hasattr(feed, 'bozo') and feed.bozo:
                logger.warning(f"[{source_name}] Feed解析警告: {getattr(feed, 'bozo_exception', 'Unknown')}")
            
            if not hasattr(feed, 'entries') or not feed.entries:
                logger.error(f"[{source_name}] 解析失败或没有找到条目")
                if attempt < max_retries - 1:
                    current_retry_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 5)
                    logger.info(f"[{source_name}] 将在{current_retry_delay:.2f}秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(current_retry_delay)
                    continue
                return False
            
            logger.info(f"[{source_name}] 成功获取，共 {len(feed.entries)} 条")
            
            notified_posts = set(source.get('notified_posts', []))
            
            for entry in feed.entries:
                try:
                    title = extract_entry_title(entry)
                    link = extract_entry_link(entry)
                    author = extract_entry_author(entry)
                    time_str = extract_entry_time(entry)
                    entry_id = extract_entry_id(entry, source_url)
                    content = extract_entry_content(entry)
                    media_links = extract_entry_media(entry, enable_media_links)
                    
                    if not title:
                        logger.debug(f"[{source_name}] 跳过无标题条目")
                        continue
                    
                    unique_key = generate_unique_key(entry_id, source_url, title, time_str)
                    
                    logger.debug(f"[{source_name}] 处理条目: title='{title[:50]}...' unique_key={unique_key}")
                    
                    if unique_key in notified_posts:
                        logger.debug(f"[{source_name}] 已通知，跳过: {unique_key}")
                        continue
                    
                    matched_keywords = []
                    for keyword in keywords:
                        if keyword.lower() in title.lower():
                            matched_keywords.append(keyword)
                    
                    if matched_keywords:
                        notified_posts.add(unique_key)
                        config_changed = True
                        
                        message_parts = [f"<b>来源：{html_escape_for_telegram(source_name)}</b>"]
                        message_parts.append(f"标题：{html_escape_for_telegram(title)}")
                        message_parts.append(f"关键词：{html_escape_for_telegram(', '.join(matched_keywords))}")
                        
                        if author:
                            message_parts.append(f"作者：{html_escape_for_telegram(author)}")
                        
                        if time_str:
                            try:
                                dt = datetime.datetime.fromisoformat(time_str)
                                formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                                message_parts.append(f"时间：{formatted_time}")
                            except Exception:
                                pass
                        
                        if content:
                            summary = content[:200] if len(content) > 200 else content
                            message_parts.append(f"摘要：{html_escape_for_telegram(summary)}")
                        
                        if link:
                            message_parts.append(f"链接：{link}")
                        
                        if media_links:
                            message_parts.append(f"媒体：{', '.join(media_links[:3])}")
                        
                        message = '\n'.join(message_parts)
                        message = truncate_for_telegram(message, 4000)
                        
                        if send_telegram_message(message, config):
                            logger.info(f"[{source_name}] 匹配关键词 {matched_keywords}，已发送通知: {title[:50]}")
                        else:
                            logger.error(f"[{source_name}] 发送通知失败: {title[:50]}")
                            notified_posts.discard(unique_key)
                            config_changed = False
                
                except Exception as e:
                    logger.error(f"[{source_name}] 处理条目时出错: {str(e)}", exc_info=True)
                    continue
            
            if config_changed:
                max_history = config.get('monitor_settings', {}).get('max_history', 100)
                source['notified_posts'] = list(notified_posts)[-max_history:]
                save_config(config)
            
            return True
            
        except requests.exceptions.Timeout:
            logger.error(f"[{source_name}] 获取超时 (尝试 {attempt+1}/{max_retries})")
        except requests.exceptions.ConnectionError:
            logger.error(f"[{source_name}] 连接失败 (尝试 {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"[{source_name}] 检查时出错: {str(e)} (尝试 {attempt+1}/{max_retries})", exc_info=True)
        
        if attempt < max_retries - 1:
            current_retry_delay = base_retry_delay * (2 ** attempt) + random.uniform(0, 5)
            logger.info(f"[{source_name}] 等待{current_retry_delay:.2f}秒后重试 ({attempt+1}/{max_retries})")
            time.sleep(current_retry_delay)
    
    return False

def monitor_loop():
    """监控主循环 - 支持per-feed轮询和并发控制"""
    logger.info("开始RSS监控")
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    detection_counter = 0
    feed_last_check = {}

    try:
        while True:
            config = load_config()
            monitor_settings = config.get('monitor_settings', {})
            min_interval = monitor_settings.get('check_interval_min', 30)
            max_interval = monitor_settings.get('check_interval_max', 60)
            max_detections = monitor_settings.get('restart_after_checks', 100)
            per_feed_min_interval = monitor_settings.get('per_feed_min_interval', 60)
            max_concurrent = monitor_settings.get('max_concurrent_feeds', 5)
            
            rss_sources = config.get('rss_sources', [])
            
            if not rss_sources:
                logger.warning("没有配置RSS源，等待配置...")
                time.sleep(60)
                continue
            
            try:
                current_time = time.time()
                sources_to_check = []
                
                for source in rss_sources:
                    source_id = source.get('id', source.get('name', 'unknown'))
                    last_check = feed_last_check.get(source_id, 0)
                    
                    if current_time - last_check >= per_feed_min_interval:
                        sources_to_check.append(source)
                
                if not sources_to_check:
                    wait_time = 10
                    logger.debug(f"所有源都在最小间隔内，等待{wait_time}秒")
                    time.sleep(wait_time)
                    continue
                
                logger.info(f"本次检查 {len(sources_to_check)} 个源")
                
                for i in range(0, len(sources_to_check), max_concurrent):
                    batch = sources_to_check[i:i+max_concurrent]
                    threads = []
                    
                    for source in batch:
                        source_name = source.get('name', 'Unknown')
                        source_id = source.get('id', source_name)
                        logger.info(f"开始检查RSS源: {source_name}")
                        
                        def check_wrapper(src, cfg):
                            try:
                                check_rss_feed(src, cfg)
                            except Exception as e:
                                logger.error(f"检查源 {src.get('name', 'Unknown')} 失败: {e}")
                        
                        t = Thread(target=check_wrapper, args=(source, config))
                        t.start()
                        threads.append(t)
                        
                        feed_last_check[source_id] = current_time + random.uniform(0, 5)
                    
                    for t in threads:
                        t.join(timeout=120)
                    
                    if i + max_concurrent < len(sources_to_check):
                        inter_batch_delay = random.uniform(2, 5)
                        logger.debug(f"批次间隔 {inter_batch_delay:.2f}秒")
                        time.sleep(inter_batch_delay)
                
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
                logger.error(f"RSS监控异常: {e}", exc_info=True)
                
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
        logger.error(f"监控循环严重异常: {e}", exc_info=True)
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
