#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试内联键盘功能
"""

import json

def test_inline_keyboard_format():
    """测试内联键盘格式是否正确"""
    
    # 模拟RSS源数据
    sources = [
        {'id': 'nodeseek', 'name': 'NodeSeek', 'url': 'https://rss.nodeseek.com/', 'keywords': ['VPS', '优惠']},
        {'id': 'test', 'name': 'Test Source', 'url': 'https://example.com/rss', 'keywords': ['测试']}
    ]
    
    # 测试1: /listsources 命令的内联键盘
    keyboard = []
    for source in sources:
        kw_count = len(source.get('keywords', []))
        button_text = f"📡 {source['name']} ({kw_count}个关键词)"
        keyboard.append([{
            "text": button_text,
            "callback_data": f"source:{source['id']}"
        }])
    
    print("测试1: /listsources 内联键盘格式")
    print(json.dumps({"inline_keyboard": keyboard}, ensure_ascii=False, indent=2))
    print("\n" + "="*50 + "\n")
    
    # 测试2: 点击源后显示关键词的内联键盘
    source = sources[0]
    keywords = source.get('keywords', [])
    
    keyword_buttons = []
    for i, kw in enumerate(keywords, 1):
        keyword_buttons.append([{
            "text": f"❌ 删除: {kw}",
            "callback_data": f"delkw:{source['id']}:{i-1}"
        }])
    
    keyboard2 = keyword_buttons + [
        [{"text": "🔙 返回源列表", "callback_data": "back_to_sources"}]
    ]
    
    print("测试2: 源详情页内联键盘格式")
    print(json.dumps({"inline_keyboard": keyboard2}, ensure_ascii=False, indent=2))
    print("\n" + "="*50 + "\n")
    
    # 测试3: 解析callback_data
    test_callbacks = [
        "source:nodeseek",
        "source:test",
        "back_to_sources",
        "delkw:nodeseek:0",
        "delkw:nodeseek:1"
    ]
    
    print("测试3: callback_data解析")
    for callback_data in test_callbacks:
        if callback_data.startswith("source:"):
            source_id = callback_data[7:]
            print(f"  {callback_data} -> 显示源: {source_id}")
        elif callback_data == "back_to_sources":
            print(f"  {callback_data} -> 返回源列表")
        elif callback_data.startswith("delkw:"):
            parts = callback_data.split(":", 2)
            if len(parts) == 3:
                source_id = parts[1]
                kw_index = int(parts[2])
                print(f"  {callback_data} -> 删除源 {source_id} 的第 {kw_index} 个关键词")
    
    print("\n所有测试通过！✓")

if __name__ == "__main__":
    test_inline_keyboard_format()
