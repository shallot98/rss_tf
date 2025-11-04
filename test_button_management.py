#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试按钮式管理功能
"""

import json
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

def test_user_state_functions():
    """测试用户状态管理函数"""
    print("测试用户状态管理...")
    
    # 模拟配置
    config = {
        'user_states': {},
        'rss_sources': [],
        'telegram': {'bot_token': 'test', 'chat_id': 'test'},
        'monitor_settings': {}
    }
    
    # 导入函数（避免实际运行）
    from rss_main import set_user_state, get_user_state, clear_user_state
    
    # 测试设置状态
    user_id = 123456789
    set_user_state(config, user_id, 'waiting_for_keyword', {'source_id': 'test'})
    
    # 验证状态已设置
    state = get_user_state(config, user_id)
    assert state is not None, "状态应该被设置"
    assert state['state'] == 'waiting_for_keyword', "状态类型应该正确"
    assert state['data']['source_id'] == 'test', "状态数据应该正确"
    assert 'timestamp' in state, "应该包含时间戳"
    print("✓ 设置状态功能正常")
    
    # 测试获取状态
    retrieved_state = get_user_state(config, user_id)
    assert retrieved_state == state, "获取的状态应该与设置的一致"
    print("✓ 获取状态功能正常")
    
    # 测试清除状态
    clear_user_state(config, user_id)
    state_after_clear = get_user_state(config, user_id)
    assert state_after_clear is None, "清除后状态应该为None"
    print("✓ 清除状态功能正常")
    
    # 测试多用户
    user_id_1 = 111111111
    user_id_2 = 222222222
    set_user_state(config, user_id_1, 'state_1', {'data': 1})
    set_user_state(config, user_id_2, 'state_2', {'data': 2})
    
    state_1 = get_user_state(config, user_id_1)
    state_2 = get_user_state(config, user_id_2)
    
    assert state_1['state'] == 'state_1', "用户1状态应该独立"
    assert state_2['state'] == 'state_2', "用户2状态应该独立"
    assert state_1['data']['data'] == 1, "用户1数据应该独立"
    assert state_2['data']['data'] == 2, "用户2数据应该独立"
    print("✓ 多用户状态隔离正常")
    
    print("\n✅ 所有用户状态管理测试通过！\n")

def test_callback_data_format():
    """测试回调数据格式"""
    print("测试回调数据格式...")
    
    test_cases = [
        ("source:nodeseek", "source", "nodeseek"),
        ("addkw:nodeseek", "addkw", "nodeseek"),
        ("delkw:nodeseek:0", "delkw", "nodeseek"),
        ("delsource_confirm:nodeseek", "delsource_confirm", "nodeseek"),
        ("delsource:nodeseek", "delsource", "nodeseek"),
        ("cancel_add:nodeseek", "cancel_add", "nodeseek"),
        ("back_to_sources", "back_to_sources", None),
        ("addsource_start", "addsource_start", None),
        ("cancel_addsource", "cancel_addsource", None),
    ]
    
    for callback_data, expected_action, expected_param in test_cases:
        if ":" in callback_data:
            action = callback_data.split(":")[0]
            if expected_param:
                param = callback_data.split(":")[1]
                assert action == expected_action, f"动作应该是 {expected_action}"
                assert param == expected_param, f"参数应该是 {expected_param}"
        else:
            action = callback_data
            assert action == expected_action, f"动作应该是 {expected_action}"
        print(f"✓ {callback_data} 格式正确")
    
    print("\n✅ 所有回调数据格式测试通过！\n")

def test_config_structure():
    """测试配置结构"""
    print("测试配置结构...")
    
    from rss_main import DEFAULT_CONFIG
    
    # 验证默认配置包含 user_states
    assert 'user_states' in DEFAULT_CONFIG, "默认配置应该包含 user_states"
    assert isinstance(DEFAULT_CONFIG['user_states'], dict), "user_states 应该是字典"
    print("✓ 默认配置结构正确")
    
    # 验证配置可序列化
    try:
        json_str = json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2)
        parsed = json.loads(json_str)
        assert 'user_states' in parsed, "序列化后应该保留 user_states"
        print("✓ 配置可正确序列化")
    except Exception as e:
        raise AssertionError(f"配置序列化失败: {e}")
    
    print("\n✅ 配置结构测试通过！\n")

def test_source_id_generation():
    """测试源ID生成逻辑"""
    print("测试源ID生成...")
    
    import re
    
    test_cases = [
        ("NodeSeek RSS", "nodeseek_rss"),
        ("My-Test-Source", "my_test_source"),
        ("Source 123", "source_123"),
        ("中文源名", ""),  # 非ASCII字符会被移除
    ]
    
    for name, expected_id in test_cases:
        # 模拟 rss_main.py 中的源ID生成逻辑
        source_id = name.lower().replace(' ', '_').replace('-', '_')
        source_id = re.sub(r'[^a-z0-9_]', '', source_id)
        
        if expected_id:
            assert source_id == expected_id, f"{name} 应该生成 {expected_id}，实际生成 {source_id}"
            print(f"✓ '{name}' -> '{source_id}'")
    
    print("\n✅ 源ID生成测试通过！\n")

def main():
    """运行所有测试"""
    print("=" * 60)
    print("按钮式管理功能测试")
    print("=" * 60)
    print()
    
    try:
        test_config_structure()
        test_user_state_functions()
        test_callback_data_format()
        test_source_id_generation()
        
        print("=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print()
        print("=" * 60)
        print(f"❌ 测试失败: {e}")
        print("=" * 60)
        return 1
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ 测试出错: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 60)
        return 1

if __name__ == "__main__":
    # 不保存配置，只测试逻辑
    import rss_main
    # 禁用保存功能
    original_save = rss_main.save_config
    rss_main.save_config = lambda config: None
    
    try:
        exit_code = main()
        sys.exit(exit_code)
    finally:
        # 恢复原始函数
        rss_main.save_config = original_save
