# 修复总结：RSS重复推送Bug

## 问题

RSS监控程序存在一个关键bug：一旦某条消息被推送过一次，就永远不会再推送，即使已经超过了24小时的去重窗口期。

## 根本原因

在 `dedup.py` 的 `DedupHistory.is_duplicate()` 方法中，当检测到历史记录中存在某个去重键时，无论该记录是在去重窗口期内还是已经过期，都会返回 `True`（标记为重复），导致所有历史中的条目永远不会被重新推送。

**问题代码（第244行）：**
```python
else:
    return True, f'old ({time_elapsed/3600:.1f}h ago, outside debounce window)'
```

## 修复方案

修改 `is_duplicate()` 方法，当条目超过去重窗口期时返回 `False`（不是重复项），允许重新推送。

**修复后的代码：**
```python
else:
    # Outside debounce window - allow re-sending
    return False, f'expired ({time_elapsed/3600:.1f}h ago, outside {self.debounce_seconds/3600:.0f}h window)'
```

## 修改的文件

### 1. `dedup.py`
- **修改行数**: 第244-248行
- **变更**: `is_duplicate()` 方法在条目超过去重窗口期时返回 `False` 而不是 `True`
- **影响**: 核心去重逻辑，允许过期条目重新推送

### 2. `test_dedup.py`
- **修改行数**: 第251-265行
- **变更**: 更新 `test_old_entry_outside_debounce()` 测试以匹配正确行为
- **影响**: 单元测试验证修复

### 3. `test_reproduce_duplicates.py`
- **修改行数**: 第324-332行
- **变更**: 更新 Scenario 6 测试，验证25小时后条目不是重复项
- **影响**: 场景测试验证修复

### 4. `rss_main.py`
- **修改行数**: 第379-381行（新增）
- **变更**: 添加调试日志，当条目超过去重窗口期被允许重新发送时记录
- **影响**: 增强可观测性，便于调试

### 5. `README.md`
- **修改行数**: 第312-313行
- **变更**: 更新去重机制说明，明确超过窗口期的条目可以重新推送
- **影响**: 文档准确性

### 6. 新增文件

- **`test_debounce_fix.py`**: 专门验证bug修复的测试脚本
- **`BUGFIX_DEBOUNCE.md`**: 详细的bug分析和修复文档

## 测试验证

### 所有测试通过 ✅

```bash
# 单元测试: 36/36 passed
python3 test_dedup.py

# 场景测试: 6/6 scenarios passed
python3 test_reproduce_duplicates.py

# Bug修复验证: All checks passed
python3 test_debounce_fix.py
```

### 核心测试用例

**时间线验证：**
- T=0h: 首次推送 ✅
- T=1h: 正确去重（在窗口期内）✅
- T=23h: 正确去重（在窗口期内）✅
- T=25h: **允许重新推送**（窗口期已过）✅ ← 修复点
- T=26h: 正确去重（刚推送过）✅

## 影响评估

### 正面影响
1. ✅ 修复了RSS条目永远不会重新推送的bug
2. ✅ 允许重要更新或价格变动的通知
3. ✅ 符合用户对"24小时去重窗口"的预期
4. ✅ 保持24小时内的去重保护

### 兼容性
- ✅ 完全向后兼容
- ✅ 无需修改配置文件
- ✅ 无需清理历史数据
- ✅ 自动从旧版本迁移

### 性能影响
- ✅ 无性能影响
- ✅ 逻辑复杂度不变
- ✅ 内存占用不变

## 实际应用场景

### 场景1: 价格更新通知
某VPS促销第一次推送后，48小时后商家更新价格：
- **修复前**: 不会推送 ❌
- **修复后**: 会推送价格更新 ✅

### 场景2: 重要公告重新置顶
重要通知24小时后被重新置顶：
- **修复前**: 用户不会收到 ❌
- **修复后**: 用户会再次收到 ✅

### 场景3: 定期更新内容
每周发布的周报或活动帖：
- **修复前**: 只有第一次推送，后续都被去重 ❌
- **修复后**: 每次都能正常推送（间隔>24h）✅

## 配置建议

### 默认配置（推荐大多数用户）
```json
{
  "monitor_settings": {
    "dedup_debounce_hours": 24,
    "dedup_history_size": 1000
  }
}
```

### 高频更新场景
如果担心重复推送，可增加窗口期：
```json
{
  "monitor_settings": {
    "dedup_debounce_hours": 48,
    "dedup_history_size": 2000
  }
}
```

### 低频更新场景
如果希望更快看到更新，可缩短窗口期：
```json
{
  "monitor_settings": {
    "dedup_debounce_hours": 12,
    "dedup_history_size": 500
  }
}
```

## 调试指南

### 启用详细日志

编辑 `/data/config.json`：
```json
{
  "monitor_settings": {
    "enable_debug_logging": true
  }
}
```

### 查看去重决策

检查 `/data/monitor.log`：

**窗口期内的去重：**
```
[NodeSeek] ⏭️ 跳过重复项: id:post-123:author:john (debounced (2.5h ago))
```

**窗口期过期的重新发送：**
```
[NodeSeek] 🔄 去重窗口已过期，允许重新发送: expired (26.3h ago, outside 24h window)
[NodeSeek] ✅ 检测到关键词 'VPS' 并发送通知
```

## 部署说明

### 升级步骤
1. 拉取最新代码
2. 无需修改配置
3. 重启监控程序即可

### 验证修复
1. 等待某个已推送过的条目在24小时后再次出现
2. 检查日志，应该看到"允许重新发送"的消息
3. 验证Telegram收到了通知

## 版本信息

- **Bug引入**: v2.1 (去重机制重构时)
- **修复版本**: v2.1.1
- **修复日期**: 2024-12-30
- **Git分支**: `fix/rss-dedup-telegram-history`

## 相关文档

- 详细bug分析: `BUGFIX_DEBOUNCE.md`
- 去重机制说明: `README.md` 第282-340行
- 去重模块代码: `dedup.py`
- 单元测试: `test_dedup.py`
- 场景测试: `test_reproduce_duplicates.py`
- 验证脚本: `test_debounce_fix.py`

## 总结

这次修复解决了一个关键的去重逻辑bug，确保RSS监控系统按照设计意图工作：

✅ **24小时内**: 有效去重，避免重复推送  
✅ **24小时后**: 允许重新推送，不错过重要更新  
✅ **自动清理**: 过期记录自动清理，节省内存  
✅ **详细日志**: 调试模式提供完整的去重决策日志  

修复已通过所有测试验证，可以安全部署到生产环境。
