# Changelog: Fix linux.do RSS 403 (UA headers + fallback)

## Overview
This update fixes HTTP 403 errors when fetching RSS feeds (particularly linux.do) by implementing improved HTTP headers, automatic fallbacks, and optional Cloudflare bypass support.

## Changes Made

### 1. Enhanced HTTP Headers (rss_main.py)
- **New function: `create_session(custom_headers=None)`**
  - Creates requests Session with modern browser-like headers
  - Default User-Agent: Chrome 120.0 on Windows 10
  - Includes Accept, Accept-Language, Accept-Encoding headers
  - Auto-generates Referer header based on feed origin
  - Supports custom header overrides per source

### 2. 403 Handling with Fallback Logic (rss_main.py)
- **New function: `fetch_feed_with_fallback(source_url, source_name, source_config, timeout=30)`**
  - Primary attempt with enhanced headers
  - **linux.do specific handling:**
    - Detects `/posts.rss` URLs
    - Automatically retries with `/latest.rss` on 403
  - **cloudscraper fallback:**
    - Activates for linux.do or when `use_cloudscraper: true` is set
    - Only runs if cloudscraper is installed
    - Bypasses Cloudflare challenges
  - **Clear logging:**
    - Reports which method succeeded (requests/cloudscraper/fallback_url)
    - Provides installation hints when cloudscraper is needed but missing

### 3. Per-Source Configuration Support
Sources now support optional fields in config.json:

```json
{
  "rss_sources": [
    {
      "id": "linux_do",
      "name": "Linux.do",
      "url": "https://linux.do/posts.rss",
      "keywords": ["VPS", "hosting"],
      "headers": {
        "Custom-Header": "value"
      },
      "use_cloudscraper": false,
      "notified_posts": [],
      "notified_authors": []
    }
  ]
}
```

- **`headers` (dict, optional):** Custom HTTP headers for this source
- **`use_cloudscraper` (bool, optional, default: false):** Force cloudscraper usage

### 4. Dependency Management (start.py)
- **Enhanced `check_dependencies()` function:**
  - Detects if any source uses linux.do or has `use_cloudscraper: true`
  - Prompts user to install cloudscraper when needed
  - Shows which sources require cloudscraper
  - Auto-installs if user confirms
  - Gracefully continues if user declines

- **Updated display functions:**
  - `show_config()` now shows `use_cloudscraper` and custom header count
  - `manage_sources()` displays cloudscraper status per source

### 5. Requirements Update
- Added `cloudscraper>=1.2.58` to requirements.txt
- Note: cloudscraper is optional but recommended for linux.do

## Usage Examples

### Example 1: linux.do with automatic fallback
```json
{
  "id": "linux_do",
  "name": "Linux.do",
  "url": "https://linux.do/posts.rss",
  "keywords": ["hosting"]
}
```
**Behavior:** 
1. Tries `/posts.rss` with enhanced headers
2. On 403, automatically retries with `/latest.rss`
3. If still 403 and cloudscraper installed, uses cloudscraper

### Example 2: Force cloudscraper usage
```json
{
  "id": "protected_site",
  "name": "Protected Site",
  "url": "https://example.com/rss",
  "use_cloudscraper": true,
  "keywords": ["tech"]
}
```
**Behavior:** Uses cloudscraper on first 403, skips standard retry

### Example 3: Custom headers
```json
{
  "id": "api_feed",
  "name": "API Feed",
  "url": "https://api.example.com/feed",
  "headers": {
    "X-API-Key": "secret123",
    "Authorization": "Bearer token"
  },
  "keywords": ["api"]
}
```
**Behavior:** Merges custom headers with default browser headers

## Logging Examples

### Success with standard requests:
```
[Linux.do] 尝试使用 requests with enhanced headers 获取: https://linux.do/posts.rss
[Linux.do] ✓ 使用标准requests成功获取feed
```

### Fallback to /latest.rss:
```
[Linux.do] 收到403 Forbidden响应
[Linux.do] 检测到linux.do /posts.rss，尝试fallback到 /latest.rss
[Linux.do] 尝试使用 requests with /latest.rss fallback 获取: https://linux.do/latest.rss
[Linux.do] ✓ 使用/latest.rss fallback成功
```

### cloudscraper bypass:
```
[Linux.do] 收到403 Forbidden响应
[Linux.do] /latest.rss仍然返回403
[Linux.do] 尝试使用cloudscraper绕过Cloudflare保护
[Linux.do] cloudscraper尝试获取: https://linux.do/latest.rss
[Linux.do] ✓ cloudscraper成功获取feed
```

### Missing cloudscraper warning:
```
[Linux.do] cloudscraper未安装。建议:
  1. 安装cloudscraper: pip install cloudscraper
  2. 或将URL更改为 https://linux.do/latest.rss
```

## Migration Guide

### For existing users:
1. No config changes required - old configs work as-is
2. Enhanced headers apply automatically to all sources
3. linux.do sources get automatic /latest.rss fallback
4. To enable cloudscraper: `pip install cloudscraper`

### For new linux.do sources:
**Recommended setup:**
```bash
# Install cloudscraper
pip install cloudscraper

# Add source via Telegram or start.py
/addsource https://linux.do/posts.rss Linux.do
/add linux.do your_keyword
```

**Alternative (without cloudscraper):**
```bash
# Use /latest.rss directly
/addsource https://linux.do/latest.rss Linux.do
```

## Testing

Run the test suite:
```bash
python3 test_rss_fetch.py
```

Tests verify:
- Module imports work
- Function signatures are correct
- Config field support
- Logging patterns
- start.py integration
- requirements.txt update

## Acceptance Criteria Met

✅ linux.do /posts.rss no longer hard-fails  
✅ Transparent fallback to /latest.rss  
✅ cloudscraper bypass when available  
✅ NodeSeek and other feeds unaffected  
✅ Clear logging with method used  
✅ Helpful prompts when cloudscraper missing  
✅ Per-source configuration support  
✅ No uncaught exceptions  
✅ Graceful degradation when cloudscraper unavailable

## Files Modified

- `rss_main.py`: Core fetch logic, session creation, fallback handling
- `start.py`: Dependency check, cloudscraper detection, display updates
- `requirements.txt`: Added cloudscraper>=1.2.58
- `test_rss_fetch.py`: New test suite (not shipped with production)
- `CHANGELOG_403_FIX.md`: This file (documentation)
