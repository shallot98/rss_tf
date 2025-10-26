#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS监控程序启动脚本
提供友好的配置界面和启动功能
"""

import os
import sys
import json
import subprocess
import time
import signal
from pathlib import Path

def print_banner():
    """打印程序横幅"""
    print("=" * 60)
    print("           RSS监控程序 - 启动向导")
    print("=" * 60)
    print()

def check_dependencies():
    """检查依赖包"""
    print("正在检查依赖包...")
    missing_packages = []
    
    try:
        import requests
        print("✓ requests 已安装")
    except ImportError:
        missing_packages.append("requests")
        print("✗ requests 未安装")
    
    try:
        import feedparser
        print("✓ feedparser 已安装")
    except ImportError:
        missing_packages.append("feedparser")
        print("✗ feedparser 未安装")
    
    try:
        import psutil
        print("✓ psutil 已安装")
    except ImportError:
        missing_packages.append("psutil")
        print("✗ psutil 未安装")
    
    if missing_packages:
        print(f"\n缺少以下依赖包，正在安装...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing_packages)
            print("✓ 依赖包安装完成")
        except subprocess.CalledProcessError:
            print("✗ 依赖包安装失败，请手动安装：")
            print(f"pip install {' '.join(missing_packages)}")
            return False
    
    config = load_config()
    sources = config.get('rss_sources', [])
    needs_cloudscraper = any(
        source.get('use_cloudscraper', False) or 'linux.do' in source.get('url', '')
        for source in sources
    )
    
    if needs_cloudscraper:
        try:
            import cloudscraper
            print("✓ cloudscraper 已安装 (用于绕过Cloudflare保护)")
        except ImportError:
            print("! cloudscraper 未安装 (可选，用于绕过Cloudflare保护)")
            print("  检测到以下情况可能需要cloudscraper:")
            for source in sources:
                if source.get('use_cloudscraper', False):
                    print(f"    - {source.get('name')} 配置了 use_cloudscraper")
                elif 'linux.do' in source.get('url', ''):
                    print(f"    - {source.get('name')} 使用 linux.do")
            
            install = input("\n是否安装cloudscraper? (y/n, 默认y): ").strip().lower()
            if install != 'n':
                try:
                    print("正在安装cloudscraper...")
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "cloudscraper"])
                    print("✓ cloudscraper 安装完成")
                except subprocess.CalledProcessError:
                    print("✗ cloudscraper 安装失败")
                    print("  提示: 可以稍后手动安装: pip install cloudscraper")
    
    print()
    return True

def load_config():
    """加载配置文件"""
    config_file = Path("data/config.json")
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            if 'telegram' not in config:
                config['telegram'] = {'bot_token': '', 'chat_id': ''}
            if 'rss_sources' not in config:
                config['rss_sources'] = []
            if 'monitor_settings' not in config:
                config['monitor_settings'] = {
                    'check_interval_min': 30,
                    'check_interval_max': 60,
                    'max_history': 100,
                    'restart_after_checks': 100
                }
            return config
        except Exception as e:
            print(f"配置文件读取失败: {e}")
    
    return {
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

def save_config(config):
    """保存配置文件"""
    config_file = Path("data/config.json")
    config_file.parent.mkdir(exist_ok=True)
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"配置文件保存失败: {e}")
        return False

def get_pid_file():
    """获取PID文件路径"""
    return Path("data/monitor.pid")

def is_monitor_running():
    """检查监控程序是否正在运行"""
    pid_file = get_pid_file()
    if not pid_file.exists():
        return False
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        import psutil
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            if "rss_main.py" in " ".join(process.cmdline()):
                return True
        return False
    except:
        return False

def stop_monitor():
    """停止监控程序"""
    pid_file = get_pid_file()
    if not pid_file.exists():
        print("监控程序未运行")
        return
    
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        
        import psutil
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            process.terminate()
            print(f"正在停止监控程序 (PID: {pid})...")
            
            try:
                process.wait(timeout=5)
                print("✓ 监控程序已停止")
            except psutil.TimeoutExpired:
                process.kill()
                print("✓ 监控程序已强制停止")
        else:
            print("监控程序进程不存在")
        
        pid_file.unlink(missing_ok=True)
        
    except Exception as e:
        print(f"停止监控程序失败: {e}")

def setup_telegram():
    """设置Telegram配置"""
    print("=== Telegram 配置 ===")
    print("请按照以下步骤获取Telegram机器人信息：")
    print("1. 在Telegram中搜索 @BotFather")
    print("2. 发送 /newbot 创建新机器人")
    print("3. 按照提示设置机器人名称")
    print("4. 获取 bot_token（类似：123456789:ABCdefGHIjklMNOpqrsTUVwxyz）")
    print("5. 将机器人添加到群组或直接与机器人对话")
    print("6. 获取 chat_id（群组ID或个人ID）")
    print()
    
    config = load_config()
    
    bot_token = input("请输入 bot_token: ").strip()
    if bot_token:
        config['telegram']['bot_token'] = bot_token
    
    chat_id = input("请输入 chat_id: ").strip()
    if chat_id:
        config['telegram']['chat_id'] = chat_id
    
    if save_config(config):
        print("✓ Telegram配置已保存")
    else:
        print("✗ Telegram配置保存失败")
    
    return config

def show_menu():
    """显示主菜单"""
    print("\n=== 主菜单 ===")
    print("1. 配置Telegram机器人")
    print("2. 查看当前配置")
    print("3. 管理RSS源")
    print("4. 启动监控程序")
    print("5. 停止监控程序")
    print("6. 查看监控状态")
    print("7. 运行诊断")
    print("8. 退出")
    print()

def show_config():
    """显示当前配置"""
    config = load_config()
    
    print("\n=== 当前配置 ===")
    print(f"Bot Token: {'已设置' if config['telegram']['bot_token'] else '未设置'}")
    print(f"Chat ID: {'已设置' if config['telegram']['chat_id'] else '未设置'}")
    
    sources = config.get('rss_sources', [])
    print(f"\nRSS源数量: {len(sources)}")
    
    if sources:
        for i, source in enumerate(sources, 1):
            kw_count = len(source.get('keywords', []))
            print(f"\n{i}. {source['name']} (ID: {source.get('id', 'N/A')})")
            print(f"   URL: {source['url']}")
            print(f"   关键词: {kw_count}个")
            if kw_count > 0:
                keywords = source.get('keywords', [])[:3]
                print(f"   示例: {', '.join(keywords)}{'...' if kw_count > 3 else ''}")
            if source.get('use_cloudscraper'):
                print(f"   使用cloudscraper: 是")
            if source.get('headers'):
                print(f"   自定义headers: {len(source.get('headers', {}))}个")
    
    settings = config.get('monitor_settings', {})
    print(f"\n监控设置:")
    print(f"  检查间隔: {settings.get('check_interval_min', 30)}-{settings.get('check_interval_max', 60)}秒")
    print(f"  最大历史: {settings.get('max_history', 100)}条")
    print(f"  重启周期: 每{settings.get('restart_after_checks', 100)}次检测")
    
    print("\n注意：源和关键词可以通过Telegram机器人指令管理")
    print("指令：/addsource, /delsource, /listsources, /add, /del, /list, /help")
    print()

def manage_sources():
    """管理RSS源"""
    config = load_config()
    
    while True:
        print("\n=== RSS源管理 ===")
        sources = config.get('rss_sources', [])
        
        if sources:
            print("\n当前RSS源:")
            for i, source in enumerate(sources, 1):
                kw_count = len(source.get('keywords', []))
                print(f"{i}. {source['name']} (ID: {source.get('id', 'N/A')})")
                print(f"   URL: {source['url']}")
                print(f"   关键词: {kw_count}个")
                if source.get('use_cloudscraper'):
                    print(f"   使用cloudscraper: 是")
        else:
            print("\n当前没有RSS源")
        
        print("\n操作:")
        print("1. 添加RSS源")
        print("2. 删除RSS源")
        print("3. 返回主菜单")
        
        choice = input("\n请选择操作 (1-3): ").strip()
        
        if choice == '1':
            url = input("请输入RSS源URL: ").strip()
            if not url:
                print("✗ URL不能为空")
                continue
            
            name = input("请输入源名称: ").strip()
            if not name:
                print("✗ 名称不能为空")
                continue
            
            source_id = name.lower().replace(' ', '_')
            
            if any(s.get('id') == source_id or s.get('name') == name for s in sources):
                print(f"✗ 源 '{name}' 已存在")
                continue
            
            new_source = {
                'id': source_id,
                'name': name,
                'url': url,
                'keywords': [],
                'notified_posts': [],
                'notified_authors': []
            }
            config['rss_sources'].append(new_source)
            
            if save_config(config):
                print(f"✓ 已添加源: {name}")
            else:
                print("✗ 保存失败")
        
        elif choice == '2':
            if not sources:
                print("✗ 没有可删除的源")
                continue
            
            try:
                idx = int(input("请输入要删除的源编号: ").strip())
                if 1 <= idx <= len(sources):
                    removed = sources.pop(idx - 1)
                    if save_config(config):
                        print(f"✓ 已删除源: {removed['name']}")
                    else:
                        print("✗ 保存失败")
                else:
                    print("✗ 无效的编号")
            except ValueError:
                print("✗ 请输入有效的数字")
        
        elif choice == '3':
            break
        else:
            print("无效选择")

def start_monitor():
    """启动监控程序"""
    config = load_config()
    
    if not config['telegram']['bot_token'] or not config['telegram']['chat_id']:
        print("✗ 请先配置Telegram机器人信息")
        return
    
    if is_monitor_running():
        print("✗ 监控程序已在运行中")
        return
    
    print("\n=== 启动监控程序 ===")
    print("程序将在后台运行，start.py退出后监控程序仍会继续运行")
    print("源和关键词可以通过Telegram机器人指令管理：")
    print("- 源管理: /addsource, /delsource, /listsources")
    print("- 关键词管理: /add <源名> <关键词>, /del <源名> <关键词>, /list [源名]")
    print("- 帮助: /help")
    print()
    
    env = os.environ.copy()
    env['TG_BOT_TOKEN'] = config['telegram']['bot_token']
    env['TG_CHAT_ID'] = config['telegram']['chat_id']
    
    try:
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            process = subprocess.Popen(
                [sys.executable, "rss_main.py"],
                env=env,
                startupinfo=startupinfo,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = subprocess.Popen(
                [sys.executable, "rss_main.py"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
        
        pid_file = get_pid_file()
        pid_file.parent.mkdir(exist_ok=True)
        with open(pid_file, 'w') as f:
            f.write(str(process.pid))
        
        print(f"✓ 监控程序已启动 (PID: {process.pid})")
        print("程序在后台运行，可以通过以下方式管理：")
        print("- 在start.py中选择'停止监控程序'")
        print("- 直接运行: python rss_main.py")
        print("- 查看日志: data/monitor.log")
        
    except Exception as e:
        print(f"启动失败: {e}")

def show_monitor_status():
    """显示监控程序状态"""
    if is_monitor_running():
        pid_file = get_pid_file()
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        print(f"✓ 监控程序正在运行 (PID: {pid})")
        
        log_file = Path("data/monitor.log")
        if log_file.exists():
            size = log_file.stat().st_size
            print(f"日志文件: data/monitor.log ({size} 字节)")
        else:
            print("日志文件: 未创建")
    else:
        print("✗ 监控程序未运行")

def run_diagnostics():
    """运行RSS诊断程序"""
    print("\n=== RSS 诊断 ===")
    print("正在运行诊断程序，这可能需要一些时间...")
    print()
    
    script_path = Path("scripts/collect_errors.py")
    if not script_path.exists():
        print("✗ 诊断脚本不存在: scripts/collect_errors.py")
        return
    
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=Path.cwd(),
            capture_output=False
        )
        
        print()
        if result.returncode == 0:
            print("✓ 诊断完成：所有源均可访问")
        else:
            print("✗ 诊断完成：检测到问题")
        
        print("\n提示: 诊断报告已保存到 data/errors/<timestamp>/ 目录")
        
    except Exception as e:
        print(f"✗ 运行诊断时出错: {e}")

def main():
    """主函数"""
    print_banner()
    
    if not check_dependencies():
        return
    
    while True:
        show_menu()
        choice = input("请选择操作 (1-8): ").strip()
        
        if choice == '1':
            setup_telegram()
        elif choice == '2':
            show_config()
        elif choice == '3':
            manage_sources()
        elif choice == '4':
            start_monitor()
        elif choice == '5':
            stop_monitor()
        elif choice == '6':
            show_monitor_status()
        elif choice == '7':
            run_diagnostics()
        elif choice == '8':
            print("再见！")
            break
        else:
            print("无效选择，请重新输入")

if __name__ == "__main__":
    main()
