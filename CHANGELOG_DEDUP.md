# Deduplication Logic Fix - Changelog

## Summary

This update completely overhauls the RSS feed deduplication system to eliminate duplicate notifications. The fix addresses all reported issues with unstable dedup keys, missing persistence, and incomplete tracking.

## What Was Fixed

### 1. Unstable Deduplication Keys ❌ → ✅

**Before:**
- Used regex-extracted post IDs from links (fragile)
- MD5 hash of raw links (tracking params caused different hashes)
- Author normalization was inconsistent

**After:**
- Priority-based ID extraction: `entry.id > entry.guid > normalized_link`
- Comprehensive URL normalization:
  - Lowercase scheme and host
  - Remove tracking parameters (utm_*, fbclid, gclid, etc.)
  - Sort query parameters alphabetically
  - Remove URL fragments (#)
  - Remove trailing slashes
- Robust author normalization

**Example:**
```
https://NodeSeek.COM/post?utm_source=twitter&id=1#comments
https://nodeseek.com/post?id=1&utm_campaign=email
```
Both now generate the **same** dedup key! ✅

### 2. No Timestamp-Based History ❌ → ✅

**Before:**
- Simple list of seen keys without timestamps
- No way to expire old entries
- Couldn't determine "how long ago" something was seen

**After:**
- Dictionary mapping keys → timestamps
- Configurable debounce window (default 24 hours)
- Automatic cleanup of entries outside debounce window
- Detailed logging of time elapsed since last seen

### 3. Non-Atomic Persistence ❌ → ✅

**Before:**
- Direct write to config file
- Risk of corruption on crash or disk full
- No fsync to ensure durability

**After:**
- Write to temp file first
- `fsync()` to ensure data on disk
- Atomic `os.replace()` to swap files
- Backup kept before replacement
- Graceful recovery from corrupted history

### 4. No Debounce Window ❌ → ✅

**Before:**
- History trimmed only by count
- Old entries could be forgotten and re-sent
- No time-based filtering

**After:**
- Configurable debounce window (default 24h)
- Entries suppress re-sends within window
- Outside window: still in history but marked differently
- Automatic cleanup of very old entries

### 5. Multi-Keyword Re-sends ❌ → ✅

**Before:**
- Entry could be sent multiple times if it matched multiple keywords

**After:**
- Per-cycle `sent_in_this_cycle` set
- Entry sent at most once per polling loop
- Even if matches 10 keywords, only 1 notification

### 6. No Debug Logging ❌ → ✅

**Before:**
- Basic logging only
- Hard to diagnose why duplicates occurred

**After:**
- Detailed debug mode (configurable)
- Logs every dedup decision:
  - Computed key
  - Normalized link
  - Decision reason (new/duplicate/debounced)
  - Time elapsed since last seen
- Easy troubleshooting

### 7. No Tests ❌ → ✅

**Before:**
- No unit tests
- Manual testing only
- Hard to verify fixes

**After:**
- 36 comprehensive unit tests
- Reproduction script with 6 real-world scenarios
- Testing documentation (TESTING.md)
- All tests passing ✅

## New Files

### 1. `dedup.py` (11KB)
Core deduplication module with:
- `normalize_url()` - URL normalization with tracking param removal
- `normalize_author()` - Author name normalization
- `extract_entry_id()` - Priority-based ID extraction
- `generate_dedup_key()` - Stable key generation with debug info
- `DedupHistory` class - History management with timestamps and debounce

### 2. `test_dedup.py` (19KB)
Comprehensive unit tests:
- 7 URL normalization tests
- 5 author normalization tests
- 3 entry ID extraction tests
- 5 dedup key generation tests
- 6 history management tests
- 2 migration & integration tests
- 4 edge case tests
- 4 reproduction scenario tests

### 3. `test_reproduce_duplicates.py` (12KB)
Reproduction script demonstrating fixes:
- Scenario 1: Tracking parameter normalization
- Scenario 2: Entry ID stability
- Scenario 3: Author differentiation
- Scenario 4: Multi-keyword single-send
- Scenario 5: Restart persistence
- Scenario 6: Debounce window behavior

### 4. `TESTING.md` (7KB)
Testing documentation covering:
- How to run unit tests
- How to run reproduction tests
- Manual testing procedures
- Integration testing
- Performance testing
- Troubleshooting guide

## Modified Files

### 1. `rss_main.py`
**Changes:**
- Import `dedup` module after logger setup
- Add new config defaults:
  - `dedup_history_size: 1000`
  - `dedup_debounce_hours: 24`
  - `enable_debug_logging: false`
- Enhanced `save_config()` with fsync for atomic writes
- New functions:
  - `load_dedup_history()` - Load/migrate history
  - `save_dedup_history()` - Save history with backward compat
- **Complete rewrite of `check_rss_feed()`**:
  - Use new dedup key generation
  - Load/save timestamped history
  - Per-cycle sent tracking
  - Cleanup old entries
  - Detailed debug logging

### 2. `README.md`
**New sections:**
- "去重机制详解" (Deduplication Details)
  - Dedup strategy explanation
  - Configuration options
  - Debug mode instructions
  - Backward compatibility notes
- Enhanced "故障排除" (Troubleshooting)
  - Duplicate push problem diagnosis
  - History corruption recovery
  - Debug logging procedures
- Updated config file structure examples
- Updated version to 2.1 with feature list

## Configuration Changes

### New Config Fields

**In `monitor_settings`:**
```json
{
  "dedup_history_size": 1000,       // Max history entries (default 1000)
  "dedup_debounce_hours": 24,       // Debounce window hours (default 24)
  "enable_debug_logging": false     // Debug mode (default false)
}
```

**In each `rss_sources` entry:**
```json
{
  "dedup_history": {
    "id:post-123:author:john": 1699999999.123,
    "link:abc123:author:jane": 1699999888.456
  },
  "notified_posts": []  // Kept for backward compatibility
}
```

## Backward Compatibility

✅ **Fully backward compatible:**
- Old `notified_posts` arrays automatically migrated
- New format saved alongside old for rollback support
- Default config values ensure no breaking changes
- Existing data directories work without modification

## Migration Process

1. First run detects old `notified_posts` format
2. Converts to timestamped `dedup_history` (assumes "now")
3. Saves both formats to config
4. Future runs use new format
5. Rollback possible by using `notified_posts`

## Performance Impact

**Improvements:**
- ✅ Fewer duplicate notifications (primary goal)
- ✅ Automatic cleanup reduces memory over time
- ✅ Atomic writes prevent corruption

**Negligible overhead:**
- URL normalization: ~0.1ms per entry
- History lookup: O(1) dict access
- History trimming: Only when exceeded max_size
- Cleanup: Only on debounce window expiry

## Test Results

All tests passing:
```
$ python3 test_dedup.py
...
Ran 36 tests in 0.092s
OK

$ python3 test_reproduce_duplicates.py
...
✅ ALL TESTS PASSED!
```

## Usage Examples

### Enable Debug Logging

Edit `data/config.json`:
```json
{
  "monitor_settings": {
    "enable_debug_logging": true
  }
}
```

View logs in `data/monitor.log`:
```
[NodeSeek] Entry analysis:
  Title: Great VPS Deal
  Link: https://nodeseek.com/post-123
  Dedup key: id:post-123:author:john
  Key type: entry_id

[NodeSeek] ⏭️ 跳过重复项: id:post-123:author:john (debounced (2.5h ago))
```

### Adjust History Size

For high-volume feeds, increase history:
```json
{
  "monitor_settings": {
    "dedup_history_size": 2000
  }
}
```

### Adjust Debounce Window

For more aggressive filtering:
```json
{
  "monitor_settings": {
    "dedup_debounce_hours": 48
  }
}
```

## Validation

### Before Fix:
- Users report repeated notifications for same posts
- Different tracking params cause duplicates
- Process restarts lose history
- No way to debug why duplicates occur

### After Fix:
- ✅ Same post never notified twice within debounce window
- ✅ Tracking params normalized away
- ✅ History persists across restarts
- ✅ Debug mode shows exact dedup decisions
- ✅ 36 unit tests verify correctness
- ✅ Reproduction script confirms scenarios fixed

## Documentation

Comprehensive docs added:
- README: Dedup section (3 pages)
- TESTING.md: Full testing guide (5 pages)
- Inline code documentation
- Docstrings for all functions
- Debug logging output format

## Acceptance Criteria

All ticket requirements met:

1. ✅ **Reproduce** - `test_reproduce_duplicates.py` demonstrates scenarios
2. ✅ **Stabilize dedup key** - Priority-based with URL normalization
3. ✅ **Persisted history** - Bounded, timestamped, atomic writes
4. ✅ **Debounce window** - Configurable, default 24h
5. ✅ **Single-send per loop** - Per-cycle tracking prevents multi-keyword sends
6. ✅ **Tests** - 36 unit tests + 6 scenario tests
7. ✅ **Observability** - Debug logging with detailed decisions
8. ✅ **Backward compatible** - Auto-migration, default settings work

## Recommendations

### For Production:
1. Keep default settings (1000 history, 24h debounce)
2. Enable debug logging only for troubleshooting
3. Monitor `data/monitor.log` after deployment
4. Verify history migration in first run

### For High-Volume Feeds:
1. Increase `dedup_history_size` to 2000-5000
2. Consider 48-72h debounce window
3. Monitor memory usage with longer history
4. Run periodic tests with `test_reproduce_duplicates.py`

### For Troubleshooting:
1. Enable `enable_debug_logging: true`
2. Check dedup keys in logs
3. Verify normalized links match expectations
4. Confirm debounce reasons (time elapsed)
5. Disable debug after fixing issues (reduces log spam)

## Future Enhancements

Potential improvements for future versions:
- [ ] Persistent stats (duplicates prevented count)
- [ ] Web UI for history inspection
- [ ] Export/import history for backup
- [ ] Per-source debounce settings
- [ ] Machine learning for near-duplicate detection
- [ ] Redis backend for distributed dedup

## Version

**Version 2.1** - Deduplication Logic Fix

Released: 2024-10-30

## Support

Questions or issues with dedup logic?
1. Check README "去重机制详解" section
2. Review TESTING.md for testing procedures
3. Enable debug logging and check logs
4. Run reproduction script to verify behavior
5. File issue with debug log excerpts
