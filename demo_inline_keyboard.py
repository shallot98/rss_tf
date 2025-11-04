#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
内联键盘功能演示脚本
展示各种场景下的内联键盘格式和交互流程
"""

import json

def print_section(title):
    """打印章节标题"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60 + "\n")

def demo_sources_list():
    """演示源列表的内联键盘"""
    print_section("场景1: 用户发送 /listsources")
    
    sources = [
        {'id': 'nodeseek', 'name': 'NodeSeek', 'keywords': ['VPS', '优惠', '服务器']},
        {'id': 'hostloc', 'name': 'HostLoc', 'keywords': ['主机', '域名']},
        {'id': 'v2ex', 'name': 'V2EX', 'keywords': ['技术']},
    ]
    
    keyboard = []
    for source in sources:
        kw_count = len(source.get('keywords', []))
        button_text = f"📡 {source['name']} ({kw_count}个关键词)"
        keyboard.append([{
            "text": button_text,
            "callback_data": f"source:{source['id']}"
        }])
    
    message = {
        "text": "<b>📡 RSS源列表</b>\n\n点击下方按钮管理对应RSS源的关键词：",
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": keyboard
        }
    }
    
    print("📱 Telegram消息内容：")
    print(json.dumps(message, ensure_ascii=False, indent=2))
    
    print("\n👤 用户看到的效果：")
    print("─────────────────────────────")
    print("📡 RSS源列表")
    print("\n点击下方按钮管理对应RSS源的关键词：")
    print("\n┌──────────────────────────┐")
    for source in sources:
        kw_count = len(source.get('keywords', []))
        print(f"│ 📡 {source['name']} ({kw_count}个关键词) │")
    print("└──────────────────────────┘")

def demo_source_detail():
    """演示源详情的内联键盘"""
    print_section("场景2: 用户点击 [📡 NodeSeek (3个关键词)]")
    
    source = {
        'id': 'nodeseek',
        'name': 'NodeSeek',
        'url': 'https://rss.nodeseek.com/',
        'keywords': ['VPS', '优惠', '服务器']
    }
    
    lines = [
        f"<b>📡 {source['name']}</b>",
        f"ID: <code>{source['id']}</code>",
        f"URL: {source['url']}",
        "\n<b>关键词列表：</b>"
    ]
    
    for i, kw in enumerate(source['keywords'], 1):
        lines.append(f"{i}. {kw}")
    
    lines.append("\n💡 <b>管理提示：</b>")
    lines.append(f"• 添加关键词: /add {source['id']} &lt;关键词&gt;")
    lines.append(f"• 删除关键词: /del {source['id']} &lt;序号或关键词&gt;")
    
    keyword_buttons = []
    for i, kw in enumerate(source['keywords'], 1):
        keyword_buttons.append([{
            "text": f"❌ 删除: {kw}",
            "callback_data": f"delkw:{source['id']}:{i-1}"
        }])
    
    keyboard = keyword_buttons + [
        [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
    ]
    
    message = {
        "text": '\n'.join(lines),
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": keyboard
        }
    }
    
    print("📱 Telegram消息内容：")
    print(json.dumps(message, ensure_ascii=False, indent=2))
    
    print("\n👤 用户看到的效果：")
    print("─────────────────────────────")
    print("📡 NodeSeek")
    print("ID: nodeseek")
    print("URL: https://rss.nodeseek.com/")
    print("\n关键词列表：")
    print("1. VPS")
    print("2. 优惠")
    print("3. 服务器")
    print("\n💡 管理提示：")
    print("• 添加关键词: /add nodeseek <关键词>")
    print("• 删除关键词: /del nodeseek <序号或关键词>")
    print("\n┌─────────────────┐")
    print("│ ❌ 删除: VPS    │")
    print("│ ❌ 删除: 优惠   │")
    print("│ ❌ 删除: 服务器 │")
    print("│ 🔙 返回源列表   │")
    print("└─────────────────┘")

def demo_delete_keyword():
    """演示删除关键词后的效果"""
    print_section("场景3: 用户点击 [❌ 删除: VPS]")
    
    print("⚙️ 后台处理：")
    print("1. 解析 callback_data: delkw:nodeseek:0")
    print("2. 从 NodeSeek 源删除索引为 0 的关键词 (VPS)")
    print("3. 保存配置文件")
    print("4. 发送确认通知: ✓ 已删除关键词: VPS")
    print("5. 刷新消息，显示更新后的关键词列表")
    
    source = {
        'id': 'nodeseek',
        'name': 'NodeSeek',
        'url': 'https://rss.nodeseek.com/',
        'keywords': ['优惠', '服务器']  # VPS已被删除
    }
    
    print("\n👤 用户看到的更新后效果：")
    print("─────────────────────────────")
    print("📡 NodeSeek")
    print("ID: nodeseek")
    print("URL: https://rss.nodeseek.com/")
    print("\n关键词列表：")
    print("1. 优惠")
    print("2. 服务器")
    print("\n💡 管理提示：")
    print("• 添加关键词: /add nodeseek <关键词>")
    print("• 删除关键词: /del nodeseek <序号或关键词>")
    print("\n┌─────────────────┐")
    print("│ ❌ 删除: 优惠   │")
    print("│ ❌ 删除: 服务器 │")
    print("│ 🔙 返回源列表   │")
    print("└─────────────────┘")
    print("\n💬 顶部会短暂显示提示: ✓ 已删除关键词: VPS")

def demo_back_to_sources():
    """演示返回源列表"""
    print_section("场景4: 用户点击 [🔙 返回源列表]")
    
    print("⚙️ 后台处理：")
    print("1. 解析 callback_data: back_to_sources")
    print("2. 重新加载源列表")
    print("3. 更新消息为源列表页面")
    
    print("\n👤 用户看到返回到源列表：")
    print("─────────────────────────────")
    print("📡 RSS源列表")
    print("\n点击下方按钮管理对应RSS源的关键词：")
    print("\n┌──────────────────────────┐")
    print("│ 📡 NodeSeek (2个关键词)  │")
    print("│ 📡 HostLoc (2个关键词)   │")
    print("│ 📡 V2EX (1个关键词)      │")
    print("└──────────────────────────┘")
    print("\n注意: NodeSeek 的关键词数已从 3 更新为 2")

def demo_no_keywords():
    """演示没有关键词的源"""
    print_section("场景5: 显示没有关键词的源")
    
    source = {
        'id': 'test',
        'name': 'Test Source',
        'url': 'https://example.com/rss',
        'keywords': []
    }
    
    lines = [
        f"<b>📡 {source['name']}</b>",
        f"ID: <code>{source['id']}</code>",
        f"URL: {source['url']}",
        "\n<b>关键词列表：</b>",
        "(暂无关键词)",
        "\n💡 <b>管理提示：</b>",
        f"• 添加关键词: /add {source['id']} &lt;关键词&gt;",
        f"• 删除关键词: /del {source['id']} &lt;序号或关键词&gt;"
    ]
    
    keyboard = [
        [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
    ]
    
    print("👤 用户看到的效果：")
    print("─────────────────────────────")
    print("📡 Test Source")
    print("ID: test")
    print("URL: https://example.com/rss")
    print("\n关键词列表：")
    print("(暂无关键词)")
    print("\n💡 管理提示：")
    print("• 添加关键词: /add test <关键词>")
    print("• 删除关键词: /del test <序号或关键词>")
    print("\n┌─────────────────┐")
    print("│ 🔙 返回源列表   │")
    print("└─────────────────┘")

def demo_workflow():
    """演示完整工作流程"""
    print_section("完整工作流程示例")
    
    print("📝 场景: 用户想要为 NodeSeek 源管理关键词")
    print("\n步骤：")
    print("1️⃣  发送 /listsources")
    print("   → 看到所有源的按钮列表")
    print()
    print("2️⃣  点击 [📡 NodeSeek (3个关键词)]")
    print("   → 看到 NodeSeek 的详细信息和关键词")
    print()
    print("3️⃣  点击 [❌ 删除: VPS]")
    print("   → VPS 关键词被删除")
    print("   → 页面自动刷新显示剩余关键词")
    print()
    print("4️⃣  发送 /add nodeseek 云服务器")
    print("   → 添加新关键词 '云服务器'")
    print()
    print("5️⃣  点击 [🔙 返回源列表]")
    print("   → 返回到源列表页面")
    print("   → 看到 [📡 NodeSeek (3个关键词)] (数量已更新)")
    print()
    print("✅ 完成！整个过程流畅自然")

def main():
    """主函数"""
    print("\n" + "🎨 内联键盘功能演示".center(60, "="))
    print("\n这个演示展示了RSS监控程序的内联键盘功能")
    print("用户可以通过点击按钮来管理RSS源和关键词\n")
    
    demo_sources_list()
    demo_source_detail()
    demo_delete_keyword()
    demo_back_to_sources()
    demo_no_keywords()
    demo_workflow()
    
    print_section("优势总结")
    print("✨ 可视化操作 - 所见即所得")
    print("🎯 精准管理 - 每个按钮对应一个操作")
    print("⚡ 即时反馈 - 操作后立即看到结果")
    print("📱 移动友好 - 适合在手机上操作")
    print("🔄 无缝切换 - 在不同页面间流畅导航")
    print("🛡️ 防止误操作 - 清晰的按钮标识")
    
    print("\n" + "="*60)
    print("演示结束！".center(60))
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
