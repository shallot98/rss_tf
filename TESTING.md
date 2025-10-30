# Testing Guide

This document explains how to test the RSS deduplication functionality.

## Unit Tests

### Running All Tests

Run the comprehensive unit test suite:

```bash
python3 test_dedup.py
```

This runs 36 unit tests covering:
- URL normalization (tracking params, query sorting, etc.)
- Author name normalization
- Entry ID extraction priority
- Dedup key generation
- History management with debounce window
- Persistence across restarts
- Corrupted history recovery
- Edge cases and error handling

### Expected Output

All tests should pass:
```
...
----------------------------------------------------------------------
Ran 36 tests in 0.XXXs

OK
```

## Reproduction Tests

### Running Reproduction Scenarios

Run the reproduction script to verify dedup logic with realistic scenarios:

```bash
python3 test_reproduce_duplicates.py
```

This tests 6 real-world scenarios:
1. **Tracking Parameters** - Same post with different utm_* parameters
2. **Entry ID Stability** - Posts with proper entry.id fields
3. **Author Differentiation** - Same link by different authors
4. **Multi-keyword Single-send** - One entry matching multiple keywords
5. **Restart Persistence** - History survives restarts
6. **Debounce Window** - Time-based duplicate suppression

### Expected Output

All scenarios should pass:
```
============================================================
✅ ALL TESTS PASSED!
============================================================

The deduplication logic is working correctly.
Duplicate RSS items will not be re-pushed.
```

## Manual Testing

### Testing with Real RSS Feeds

1. **Enable debug logging** in `data/config.json`:
   ```json
   {
     "monitor_settings": {
       "enable_debug_logging": true
     }
   }
   ```

2. **Start the monitor**:
   ```bash
   python3 start.py
   ```

3. **Check logs** at `data/monitor.log` for dedup decisions:
   ```
   [源名称] Entry analysis:
     Title: Example Post
     Link: https://example.com/post
     Dedup key: id:post-123:author:john
     Key type: entry_id
   ```

4. **Verify duplicates are skipped**:
   ```
   [源名称] ⏭️ 跳过重复项: id:post-123:author:john (debounced (2.5h ago))
   ```

### Testing URL Normalization

Test URL normalization manually:

```python
from dedup import normalize_url

# These should all normalize to the same URL
url1 = "HTTPS://Example.COM/post?utm_source=twitter&id=1#section"
url2 = "https://example.com/post?id=1&utm_campaign=email"
url3 = "https://example.com/post?id=1"

print(normalize_url(url1))
print(normalize_url(url2))
print(normalize_url(url3))
# All should output: https://example.com/post?id=1
```

### Testing Dedup Key Generation

Test key generation with mock entries:

```python
from unittest.mock import Mock
from dedup import generate_dedup_key

# Create mock entry
entry = Mock()
entry.id = "post-123"
entry.author = "John Doe"
entry.link = "https://example.com/post-123?utm_source=feed"

key, debug_info = generate_dedup_key(entry)
print(f"Dedup key: {key}")
print(f"Key type: {debug_info['key_type']}")
print(f"Author normalized: {debug_info['author_normalized']}")
```

## Integration Testing

### Testing with Docker

1. **Build the image**:
   ```bash
   docker build -t rss_monitor:test .
   ```

2. **Run with test environment**:
   ```bash
   docker run --rm \
     -e TG_BOT_TOKEN=your_token \
     -e TG_CHAT_ID=your_chat_id \
     -v $(pwd)/test_data:/data \
     rss_monitor:test
   ```

3. **Verify in logs**:
   ```bash
   tail -f test_data/monitor.log
   ```

### Testing History Persistence

1. **Start monitor and let it process some entries**
2. **Stop the monitor**
3. **Check `data/config.json` for dedup_history**:
   ```json
   {
     "dedup_history": {
       "id:post-123:author:john": 1699999999.123
     }
   }
   ```
4. **Restart monitor**
5. **Verify entries are still marked as duplicates** in logs

### Testing Corrupted History Recovery

1. **Stop the monitor**
2. **Corrupt the history** in `data/config.json`:
   ```json
   {
     "dedup_history": "corrupted data"
   }
   ```
3. **Restart monitor**
4. **Check logs** - should see:
   ```
   WARNING: Failed to load dedup_history: ..., starting fresh
   ```
5. **Verify monitor continues to work**

## Performance Testing

### History Size Limits

Test with large history:

```python
from dedup import DedupHistory
import time

hist = DedupHistory(max_size=1000, debounce_hours=24)
current_time = time.time()

# Add 2000 entries
for i in range(2000):
    hist.mark_seen(f"key-{i}", current_time + i)

# Should be trimmed to 1000
print(f"History size: {hist.size()}")
assert hist.size() == 1000
```

### Cleanup Performance

Test cleanup of old entries:

```python
from dedup import DedupHistory
import time

hist = DedupHistory(max_size=1000, debounce_hours=24)
current_time = time.time()

# Add old and new entries
for i in range(500):
    hist.mark_seen(f"old-{i}", current_time - (30 * 3600))  # 30h ago
    hist.mark_seen(f"new-{i}", current_time)  # Now

print(f"Before cleanup: {hist.size()}")
hist.cleanup_old_entries(current_time)
print(f"After cleanup: {hist.size()}")
# Should only keep recent entries
```

## Continuous Testing

### Pre-commit Testing

Add to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
echo "Running dedup tests..."
python3 test_dedup.py || exit 1
python3 test_reproduce_duplicates.py || exit 1
echo "All tests passed!"
```

### Automated Testing

Set up periodic testing:

```bash
# Run tests daily
0 0 * * * cd /path/to/project && python3 test_dedup.py >> test.log 2>&1
```

## Troubleshooting Tests

### Import Errors

If tests fail with import errors:
```bash
pip install -r requirements.txt
```

### Permission Errors

If tests fail with permission errors on `/data`:
- Tests use in-memory structures, shouldn't need `/data`
- Check if rss_main.py is being imported unnecessarily
- Use `python3 -m py_compile` for syntax checks instead

### Test Failures

If tests fail:
1. Check Python version (3.7+)
2. Verify all dependencies installed
3. Check for conflicting `dedup.py` files
4. Review test output for specific assertion failures
5. Enable verbose mode: `python3 test_dedup.py -v`

## Test Coverage

Current test coverage:
- ✅ URL normalization (7 tests)
- ✅ Author normalization (5 tests)
- ✅ Entry ID extraction (3 tests)
- ✅ Dedup key generation (5 tests)
- ✅ History management (6 tests)
- ✅ Migration & integration (2 tests)
- ✅ Edge cases (4 tests)
- ✅ Reproduction scenarios (4 tests)

**Total: 36 tests**

## Adding New Tests

To add tests for new scenarios:

1. Add test methods to appropriate class in `test_dedup.py`
2. Use descriptive test names: `test_<scenario>_<expected_behavior>`
3. Include docstrings explaining the test
4. Use assertions to verify behavior
5. Run full test suite to ensure no regressions

Example:

```python
def test_new_scenario(self):
    """Test description"""
    # Setup
    hist = DedupHistory(max_size=100, debounce_hours=24)
    
    # Execute
    result = hist.some_method()
    
    # Verify
    self.assertEqual(result, expected_value)
```
