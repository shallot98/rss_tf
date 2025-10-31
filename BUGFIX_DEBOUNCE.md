# Bug Fix: 重复推送同一条信息

## 问题描述

RSS 监控系统存在一个严重bug：一旦某条RSS消息被推送过一次，就会永远不会再推送，即使已经过了去重窗口期（24小时）。

### 症状

- 第一次发现新帖子时正常推送 ✅
- 24小时内的重复项正确被去重 ✅
- **但是24小时后，同一帖子更新或重新出现时不会再次推送** ❌

### 根本原因

在 `dedup.py` 的 `is_duplicate()` 方法中，当检测到历史记录中存在某个去重键时，无论是否超过去重窗口期，都会返回 `True`（表示是重复项）。

**错误的代码逻辑（修复前）：**

```python
def is_duplicate(self, key: str, current_time: Optional[float] = None) -> Tuple[bool, str]:
    if key not in self.history:
        return False, 'new'
    
    last_seen = self.history[key]
    time_elapsed = current_time - last_seen
    
    if time_elapsed < self.debounce_seconds:
        return True, f'debounced ({time_elapsed/3600:.1f}h ago)'
    else:
        # BUG: 这里返回 True，导致超过窗口期的条目永远不会再推送
        return True, f'old ({time_elapsed/3600:.1f}h ago, outside debounce window)'
```

## 修复方案

### 代码修改

修改 `dedup.py` 中的 `is_duplicate()` 方法，当条目超过去重窗口期时返回 `False`（不是重复项，允许推送）：

```python
def is_duplicate(self, key: str, current_time: Optional[float] = None) -> Tuple[bool, str]:
    if current_time is None:
        current_time = time.time()
    
    if key not in self.history:
        return False, 'new'
    
    last_seen = self.history[key]
    time_elapsed = current_time - last_seen
    
    if time_elapsed < self.debounce_seconds:
        return True, f'debounced ({time_elapsed/3600:.1f}h ago)'
    else:
        # FIX: 超过去重窗口期，返回 False 允许重新推送
        return False, f'expired ({time_elapsed/3600:.1f}h ago, outside {self.debounce_seconds/3600:.0f}h window)'
```

### 关键变化

1. **第244行**：`return True` → `return False`
2. **原因描述**：`'old (..., outside debounce window)'` → `'expired (..., outside 24h window)'`
3. **增强文档**：明确说明返回值的含义

## 验证测试

### 测试场景：去重窗口期行为

```python
# 创建24小时去重窗口的历史管理器
hist = DedupHistory(max_size=1000, debounce_hours=24)
current_time = time.time()

# T=0h: 第一次推送
hist.mark_seen("key1", current_time)
is_dup, reason = hist.is_duplicate("key1", current_time)
# 结果: False (new) ✅ 允许推送

# T=1h: 1小时后再次出现
is_dup, reason = hist.is_duplicate("key1", current_time + 3600)
# 结果: True (debounced (1.0h ago)) ✅ 正确去重

# T=23h: 23小时后再次出现
is_dup, reason = hist.is_duplicate("key1", current_time + 23 * 3600)
# 结果: True (debounced (23.0h ago)) ✅ 正确去重

# T=25h: 25小时后再次出现（超过24小时窗口）
is_dup, reason = hist.is_duplicate("key1", current_time + 25 * 3600)
# 修复前: True (old (25.0h ago, outside debounce window)) ❌ 错误去重
# 修复后: False (expired (25.0h ago, outside 24h window)) ✅ 允许推送
```

### 运行测试验证

```bash
# 运行专门的bug修复测试
python3 test_debounce_fix.py

# 运行完整的单元测试
python3 test_dedup.py

# 运行场景重现测试
python3 test_reproduce_duplicates.py
```

## 影响范围

### 修改的文件

1. **dedup.py**
   - `is_duplicate()` 方法：修复返回值逻辑
   - 增强文档字符串

2. **test_dedup.py**
   - `test_old_entry_outside_debounce()` 测试：更新断言以匹配正确行为

3. **test_reproduce_duplicates.py**
   - Scenario 6测试：更新断言以匹配正确行为

4. **rss_main.py**
   - 增加调试日志：当条目超过去重窗口期被允许重新发送时记录

5. **README.md**
   - 更新去重机制说明：明确说明窗口期外的行为

### 新增的文件

- **test_debounce_fix.py**：专门验证bug修复的测试脚本

## 使用场景

### 场景1：价格更新提醒

某个VPS促销帖子第一次发布时推送了通知。48小时后，商家更新了价格，帖子重新出现在RSS源顶部：

- **修复前**：不会推送（永远被去重）❌
- **修复后**：会再次推送（超过24小时窗口）✅

### 场景2：重要通知重推

某个重要通知24小时后被重新置顶：

- **修复前**：用户不会收到通知（被去重）❌
- **修复后**：用户会再次收到通知 ✅

### 场景3：定期更新的帖子

某个版主每周发布的周报帖子：

- **修复前**：只有第一次会推送，后续周报都被去重 ❌
- **修复后**：每次周报都会正常推送（间隔超过24小时）✅

## 配置建议

### 默认配置（推荐）

```json
{
  "monitor_settings": {
    "dedup_debounce_hours": 24,
    "dedup_history_size": 1000
  }
}
```

- 24小时内避免重复推送
- 24小时后允许重新推送更新内容

### 高频监控场景

如果RSS源更新频繁，可以增加去重窗口期：

```json
{
  "monitor_settings": {
    "dedup_debounce_hours": 48,
    "dedup_history_size": 2000
  }
}
```

### 低频监控场景

如果RSS源更新很慢，可以缩短去重窗口期：

```json
{
  "monitor_settings": {
    "dedup_debounce_hours": 12,
    "dedup_history_size": 500
  }
}
```

## 调试指南

### 启用调试日志

编辑 `data/config.json`：

```json
{
  "monitor_settings": {
    "enable_debug_logging": true
  }
}
```

### 查看去重决策

检查 `data/monitor.log` 中的去重日志：

```
[NodeSeek] Entry analysis:
  Title: Great VPS Deal
  Link: https://nodeseek.com/post-123
  Dedup key: id:post-123:author:john
  Key type: entry_id

[NodeSeek] ⏭️ 跳过重复项: id:post-123:author:john (debounced (2.5h ago))
```

或者当窗口期过期时：

```
[NodeSeek] Entry analysis:
  Title: Great VPS Deal - Price Update
  Link: https://nodeseek.com/post-123
  Dedup key: id:post-123:author:john
  Key type: entry_id

[NodeSeek] 🔄 去重窗口已过期，允许重新发送: expired (26.3h ago, outside 24h window)
[NodeSeek] ✅ 检测到关键词 'VPS' 并发送通知
```

## 兼容性

- ✅ **向后兼容**：修复不影响现有配置文件
- ✅ **数据迁移**：自动从旧格式迁移
- ✅ **无需操作**：修复后直接生效，无需清理历史记录

## 版本信息

- **Bug引入版本**：2.1（去重机制重构时引入）
- **修复版本**：2.1.1
- **修复日期**：2024-12-30

## 总结

这个bug修复确保了RSS监控系统的去重机制按预期工作：

- ✅ 24小时内有效去重，避免重复推送
- ✅ 24小时后允许重新推送，不会错过重要更新
- ✅ 自动清理过期记录，节省内存
- ✅ 详细的调试日志，便于问题排查

## 相关文件

- 核心逻辑：`dedup.py`
- 主程序：`rss_main.py`
- 单元测试：`test_dedup.py`
- 场景测试：`test_reproduce_duplicates.py`
- 验证脚本：`test_debounce_fix.py`
- 使用文档：`README.md`
- 测试文档：`TESTING.md`
