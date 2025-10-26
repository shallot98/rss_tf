#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS Diagnostics Script
Detects RSS fetch errors and outputs structured reports for troubleshooting.
"""

import os
import sys
import json
import datetime
import platform
import re
import glob
from pathlib import Path

# Add parent directory to path to allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

# Determine data directory based on OS
if os.name == 'nt':
    DATA_DIR = os.path.join(os.getcwd(), 'data')
else:
    # Try /data first (Docker), fallback to ./data if not accessible
    if os.path.exists('/data') and os.access('/data', os.W_OK):
        DATA_DIR = '/data'
    else:
        DATA_DIR = os.path.join(os.getcwd(), 'data')

CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')


def mask_credentials(text):
    """Mask credentials in URLs and environment variables"""
    # Mask credentials in URLs (e.g., http://user:pass@proxy.com)
    text = re.sub(r'(https?://)[^:]+:[^@]+@', r'\1***:***@', text)
    return text


def load_config():
    """Load configuration from data directory"""
    if not os.path.exists(CONFIG_FILE):
        return None
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return None


def collect_log_errors(errors_dir):
    """Aggregate ERROR/CRITICAL lines from logs with +/-3 lines of context"""
    logs_pattern = os.path.join(DATA_DIR, 'logs', '*.log')
    main_log = os.path.join(DATA_DIR, 'monitor.log')
    
    log_files = glob.glob(logs_pattern)
    if os.path.exists(main_log):
        log_files.append(main_log)
    
    if not log_files:
        errors_log_path = os.path.join(errors_dir, 'errors.log')
        with open(errors_log_path, 'w', encoding='utf-8') as f:
            f.write("No log files found.\n")
        return 0
    
    error_output = []
    error_count = 0
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            error_output.append(f"\n{'='*80}\n")
            error_output.append(f"Log file: {log_file}\n")
            error_output.append(f"{'='*80}\n\n")
            
            # Find ERROR and CRITICAL lines with context
            for i, line in enumerate(lines):
                if ' - ERROR - ' in line or ' - CRITICAL - ' in line:
                    error_count += 1
                    # Add context: 3 lines before and 3 lines after
                    start = max(0, i - 3)
                    end = min(len(lines), i + 4)
                    
                    error_output.append(f"[Error #{error_count}] Line {i+1}:\n")
                    error_output.append('-' * 80 + '\n')
                    for j in range(start, end):
                        prefix = '>>> ' if j == i else '    '
                        error_output.append(f"{prefix}{lines[j]}")
                    error_output.append('-' * 80 + '\n\n')
        
        except Exception as e:
            error_output.append(f"Error reading {log_file}: {e}\n\n")
    
    errors_log_path = os.path.join(errors_dir, 'errors.log')
    with open(errors_log_path, 'w', encoding='utf-8') as f:
        if error_count == 0:
            f.write("No ERROR or CRITICAL log entries found.\n")
        else:
            f.write(f"Found {error_count} error entries:\n\n")
            f.writelines(error_output)
    
    return error_count


def create_browser_headers(referer=None):
    """Create browser-like headers for RSS fetch"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    if referer:
        headers['Referer'] = referer
    
    return headers


def test_source_fetch(source, errors_dir):
    """
    Test RSS source with progressive fallback strategies.
    Returns (success, report_lines)
    """
    source_name = source.get('name', 'Unknown')
    source_url = source.get('url', '')
    
    report = []
    report.append(f"RSS Source Diagnostics: {source_name}")
    report.append("=" * 80)
    report.append(f"URL: {source_url}")
    report.append(f"Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("\n")
    
    if not source_url:
        report.append("ERROR: No URL configured for this source\n")
        return False, report
    
    from urllib.parse import urlparse
    parsed_url = urlparse(source_url)
    referer = f"{parsed_url.scheme}://{parsed_url.netloc}/" if parsed_url.netloc else None
    
    is_posts_rss = parsed_url.path.endswith('/posts.rss')
    success = False
    response = None
    
    # Test 1: Standard requests with browser headers
    report.append("Test 1: Standard requests with browser headers")
    report.append("-" * 80)
    
    try:
        headers = create_browser_headers(referer)
        report.append(f"Headers sent:")
        for key, value in headers.items():
            report.append(f"  {key}: {value}")
        report.append("")
        
        session = requests.Session()
        session.headers.update(headers)
        response = session.get(source_url, timeout=30)
        
        report.append(f"Status Code: {response.status_code}")
        report.append(f"Response Headers:")
        for key, value in list(response.headers.items())[:10]:
            report.append(f"  {key}: {value}")
        
        content_preview = response.text[:200] if response.text else "(empty)"
        report.append(f"\nResponse preview (first 200 chars):")
        report.append(f"  {content_preview}")
        report.append("")
        
        if response.status_code == 200:
            report.append("✓ SUCCESS: Fetched successfully with standard requests\n")
            success = True
        else:
            report.append(f"✗ FAILED: Status code {response.status_code}\n")
    
    except Exception as e:
        report.append(f"✗ EXCEPTION: {type(e).__name__}: {str(e)}\n")
        response = None
    
    # Test 2: Fallback to /latest.rss for Discourse sites
    should_test2 = (not success and is_posts_rss and response is not None and response.status_code >= 400)
    
    if should_test2:
        report.append("Test 2: Fallback to /latest.rss")
        report.append("-" * 80)
        
        fallback_url = source_url.replace('/posts.rss', '/latest.rss')
        report.append(f"Fallback URL: {fallback_url}")
        report.append(f"Reason: Detected /posts.rss endpoint with {response.status_code} error\n")
        
        try:
            headers = create_browser_headers(referer)
            session = requests.Session()
            session.headers.update(headers)
            response = session.get(fallback_url, timeout=30)
            
            report.append(f"Status Code: {response.status_code}")
            content_preview = response.text[:200] if response.text else "(empty)"
            report.append(f"Response preview (first 200 chars):")
            report.append(f"  {content_preview}")
            report.append("")
            
            if response.status_code == 200:
                report.append("✓ SUCCESS: /latest.rss fallback worked!\n")
                report.append(f"RECOMMENDATION: Update source URL to {fallback_url}\n")
                success = True
            else:
                report.append(f"✗ FAILED: Status code {response.status_code}\n")
        
        except Exception as e:
            report.append(f"✗ EXCEPTION: {type(e).__name__}: {str(e)}\n")
    
    # Test 3: cloudscraper (if available)
    if not success and response is not None and response.status_code in [403, 503]:
        report.append("Test 3: cloudscraper (bypass Cloudflare)")
        report.append("-" * 80)
        
        try:
            import cloudscraper
            report.append("cloudscraper is available, attempting bypass...")
            
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
            
            test_url = fallback_url if (is_posts_rss and 'fallback_url' in locals()) else source_url
            report.append(f"Testing URL: {test_url}\n")
            
            response = scraper.get(test_url, timeout=30)
            
            report.append(f"Status Code: {response.status_code}")
            content_preview = response.text[:200] if response.text else "(empty)"
            report.append(f"Response preview (first 200 chars):")
            report.append(f"  {content_preview}")
            report.append("")
            
            if response.status_code == 200:
                report.append("✓ SUCCESS: cloudscraper successfully bypassed protection!\n")
                report.append("RECOMMENDATION: Install cloudscraper and set 'use_cloudscraper': true in source config\n")
                success = True
            else:
                report.append(f"✗ FAILED: Status code {response.status_code}\n")
        
        except ImportError:
            report.append("✗ cloudscraper not installed")
            report.append("  Install with: pip install cloudscraper\n")
        except Exception as e:
            report.append(f"✗ EXCEPTION: {type(e).__name__}: {str(e)}\n")
    
    # Final status
    report.append("\n" + "=" * 80)
    if success:
        report.append("FINAL RESULT: ✓ SUCCESS")
    else:
        report.append("FINAL RESULT: ✗ FAILED")
        report.append("\nRECOMMENDATIONS:")
        if response is not None and response.status_code == 403:
            report.append("  - Status 403 (Forbidden) detected")
            report.append("  - Site may be using Cloudflare or anti-bot protection")
            report.append("  - Try installing cloudscraper: pip install cloudscraper")
            if is_posts_rss:
                report.append(f"  - Try using /latest.rss instead: {source_url.replace('/posts.rss', '/latest.rss')}")
        elif response is not None and response.status_code == 404:
            report.append("  - Status 404 (Not Found) - URL may be incorrect")
            report.append("  - Verify the RSS feed URL is still valid")
        elif response is not None and response.status_code >= 500:
            report.append(f"  - Status {response.status_code} (Server Error) - Target site may be down")
            report.append("  - Try again later")
    
    report.append("=" * 80)
    
    # Write source report
    safe_name = re.sub(r'[^\w\-]', '_', source_name)
    source_report_path = os.path.join(errors_dir, f"{safe_name}.txt")
    with open(source_report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report))
    
    return success, report


def collect_environment_info(errors_dir):
    """Collect environment information"""
    env_info = []
    
    env_info.append("Environment Information")
    env_info.append("=" * 80)
    env_info.append(f"Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    env_info.append(f"Python Version: {platform.python_version()}")
    env_info.append(f"Platform: {platform.platform()}")
    env_info.append(f"Architecture: {platform.machine()}")
    env_info.append("\n")
    
    # Package versions
    env_info.append("Installed Packages:")
    env_info.append("-" * 80)
    
    packages = ['requests', 'feedparser', 'psutil', 'cloudscraper']
    for package in packages:
        try:
            mod = __import__(package)
            version = getattr(mod, '__version__', 'unknown')
            env_info.append(f"  {package}: {version}")
        except ImportError:
            env_info.append(f"  {package}: NOT INSTALLED")
    env_info.append("\n")
    
    # Proxy settings
    env_info.append("Proxy Settings:")
    env_info.append("-" * 80)
    http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
    https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    
    if http_proxy:
        env_info.append(f"  HTTP_PROXY: {mask_credentials(http_proxy)}")
    else:
        env_info.append("  HTTP_PROXY: Not set")
    
    if https_proxy:
        env_info.append(f"  HTTPS_PROXY: {mask_credentials(https_proxy)}")
    else:
        env_info.append("  HTTPS_PROXY: Not set")
    env_info.append("\n")
    
    # Data directory info
    env_info.append("Data Directory:")
    env_info.append("-" * 80)
    env_info.append(f"  Path: {DATA_DIR}")
    env_info.append(f"  Exists: {os.path.exists(DATA_DIR)}")
    if os.path.exists(DATA_DIR):
        try:
            files = os.listdir(DATA_DIR)
            env_info.append(f"  Files: {len(files)}")
            env_info.append(f"  Contents: {', '.join(files[:10])}")
        except:
            env_info.append("  Contents: Unable to list")
    env_info.append("\n")
    
    env_path = os.path.join(errors_dir, 'environment.txt')
    with open(env_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(env_info))
    
    return env_info


def generate_summary(errors_dir, source_results, error_count):
    """Generate summary report with pass/fail counts and recommendations"""
    summary = []
    
    summary.append("RSS Diagnostics Summary Report")
    summary.append("=" * 80)
    summary.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    summary.append(f"Data Directory: {DATA_DIR}")
    summary.append("\n")
    
    # Log errors summary
    summary.append("Log Analysis:")
    summary.append("-" * 80)
    if error_count == 0:
        summary.append("  ✓ No ERROR or CRITICAL entries found in logs")
    else:
        summary.append(f"  ✗ Found {error_count} ERROR/CRITICAL entries")
        summary.append(f"  See errors.log for details")
    summary.append("\n")
    
    # Source test results
    summary.append("RSS Source Test Results:")
    summary.append("-" * 80)
    
    if not source_results:
        summary.append("  No RSS sources configured")
    else:
        passed = sum(1 for success, _ in source_results.values() if success)
        failed = len(source_results) - passed
        
        summary.append(f"  Total Sources: {len(source_results)}")
        summary.append(f"  Passed: {passed}")
        summary.append(f"  Failed: {failed}")
        summary.append("\n")
        
        for source_name, (success, _) in source_results.items():
            status = "✓ PASS" if success else "✗ FAIL"
            summary.append(f"  {status} - {source_name}")
        
        summary.append("\n")
    
    # Overall recommendations
    summary.append("Recommendations:")
    summary.append("-" * 80)
    
    failed_sources = [name for name, (success, _) in source_results.items() if not success]
    
    if not failed_sources:
        summary.append("  ✓ All sources are accessible!")
        summary.append("  No immediate action required.")
    else:
        summary.append(f"  {len(failed_sources)} source(s) failed to fetch:")
        for name in failed_sources:
            safe_name = re.sub(r'[^\w\-]', '_', name)
            summary.append(f"    - {name} (see {safe_name}.txt for details)")
        
        summary.append("\n  General troubleshooting steps:")
        summary.append("    1. Check environment.txt for missing packages")
        summary.append("    2. Review individual source reports for specific errors")
        summary.append("    3. Consider installing cloudscraper for Cloudflare-protected sites")
        summary.append("    4. For Discourse sites (linux.do), try /latest.rss instead of /posts.rss")
        summary.append("    5. Check if proxy settings are needed")
        summary.append("    6. Verify RSS feed URLs are still valid")
    
    summary.append("\n" + "=" * 80)
    summary.append(f"Report Location: {errors_dir}")
    summary.append("=" * 80)
    
    summary_path = os.path.join(errors_dir, 'summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary))
    
    # Also print to console
    print('\n'.join(summary))
    
    return len(failed_sources) == 0


def main():
    """Main diagnostics function"""
    print("=" * 80)
    print("RSS Monitor Diagnostics")
    print("=" * 80)
    print()
    
    # Create timestamped errors directory
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    errors_dir = os.path.join(DATA_DIR, 'errors', timestamp)
    
    try:
        os.makedirs(errors_dir, exist_ok=True)
        print(f"Created diagnostics directory: {errors_dir}")
        print()
    except Exception as e:
        print(f"Error creating diagnostics directory: {e}")
        return 1
    
    # Collect environment info
    print("Collecting environment information...")
    collect_environment_info(errors_dir)
    print("  ✓ environment.txt created")
    print()
    
    # Aggregate log errors
    print("Scanning logs for errors...")
    error_count = collect_log_errors(errors_dir)
    print(f"  ✓ errors.log created ({error_count} errors found)")
    print()
    
    # Load config and test each source
    print("Loading configuration...")
    config = load_config()
    
    if not config:
        print("  ✗ Unable to load config file")
        print(f"  Expected location: {CONFIG_FILE}")
        source_results = {}
    else:
        sources = config.get('rss_sources', [])
        print(f"  ✓ Found {len(sources)} RSS source(s)")
        print()
        
        if sources:
            print("Testing RSS sources...")
            print("-" * 80)
        
        source_results = {}
        for i, source in enumerate(sources, 1):
            source_name = source.get('name', f'Source {i}')
            print(f"\n[{i}/{len(sources)}] Testing {source_name}...")
            success, report = test_source_fetch(source, errors_dir)
            source_results[source_name] = (success, report)
            
            status = "✓ SUCCESS" if success else "✗ FAILED"
            print(f"  {status}")
        
        print()
        print("-" * 80)
        print()
    
    # Generate summary
    print("Generating summary report...")
    all_passed = generate_summary(errors_dir, source_results, error_count)
    print()
    
    # Return appropriate exit code
    if all_passed and error_count == 0:
        print("✓ Diagnostics complete: All sources accessible, no errors in logs")
        return 0
    else:
        print("✗ Diagnostics complete: Issues detected (see reports for details)")
        return 1


if __name__ == '__main__':
    sys.exit(main())
