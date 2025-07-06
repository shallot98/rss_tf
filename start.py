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
    
    print()
    return True

def load_config():
    """加载配置文件"""
    config_file = Path("data/config.json")
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"配置文件读取失败: {e}")
    
    return {
        'keywords': [],
        'notified_entries': {},
        'telegram': {
            'bot_token': '',
            'chat_id': ''
        }
    }

def save_config(config):
    """保存配置文件"""
    config_file = Path("data/config.json")
    config_file.parent.mkdir(exist_ok=True)
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
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
        
        # 检查进程是否存在
        import psutil
        if psutil.pid_exists(pid):
            process = psutil.Process(pid)
            # 检查是否是我们的监控程序
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
            
            # 等待进程结束
            try:
                process.wait(timeout=5)
                print("✓ 监控程序已停止")
            except psutil.TimeoutExpired:
                process.kill()
                print("✓ 监控程序已强制停止")
        else:
            print("监控程序进程不存在")
        
        # 删除PID文件
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
    print("3. 启动监控程序")
    print("4. 停止监控程序")
    print("5. 查看监控状态")
    print("6. 退出")
    print()

def show_config():
    """显示当前配置"""
    config = load_config()
    
    print("\n=== 当前配置 ===")
    print(f"Bot Token: {'已设置' if config['telegram']['bot_token'] else '未设置'}")
    print(f"Chat ID: {'已设置' if config['telegram']['chat_id'] else '未设置'}")
    print(f"关键词数量: {len(config['keywords'])}")
    
    if config['keywords']:
        print("关键词列表:")
        for i, keyword in enumerate(config['keywords'], 1):
            print(f"  {i}. {keyword}")
    
    print("注意：关键词可以通过Telegram机器人指令管理")
    print("指令：/add 关键词、/del 关键词、/list、/help")
    print()

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
    print("关键词可以通过Telegram机器人指令管理：")
    print("- /add 关键词：添加关键词")
    print("- /del 关键词：删除关键词")
    print("- /list：查看所有关键词")
    print("- /help：查看帮助")
    print()
    
    # 设置环境变量
    env = os.environ.copy()
    env['TG_BOT_TOKEN'] = config['telegram']['bot_token']
    env['TG_CHAT_ID'] = config['telegram']['chat_id']
    
    try:
        # 在后台启动监控程序
        if sys.platform == "win32":
            # Windows系统
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
            # Linux/macOS系统
            process = subprocess.Popen(
                [sys.executable, "rss_main.py"],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid
            )
        
        # 保存PID到文件
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
        
        # 显示日志文件信息
        log_file = Path("data/monitor.log")
        if log_file.exists():
            size = log_file.stat().st_size
            print(f"日志文件: data/monitor.log ({size} 字节)")
        else:
            print("日志文件: 未创建")
    else:
        print("✗ 监控程序未运行")

def main():
    """主函数"""
    print_banner()
    
    # 检查依赖
    if not check_dependencies():
        return
    
    while True:
        show_menu()
        choice = input("请选择操作 (1-6): ").strip()
        
        if choice == '1':
            setup_telegram()
        elif choice == '2':
            show_config()
        elif choice == '3':
            start_monitor()
        elif choice == '4':
            stop_monitor()
        elif choice == '5':
            show_monitor_status()
        elif choice == '6':
            print("再见！")
            break
        else:
            print("无效选择，请重新输入")

if __name__ == "__main__":
    main() 