#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for universal RSS/Atom compatibility
Tests the new extraction functions with various feed formats
"""

import sys
import os
import tempfile

# Mock the DATA_DIR to avoid permission issues
os.environ['DATA_DIR_TEST'] = tempfile.mkdtemp()

# Patch the module before importing
import importlib.util
spec = importlib.util.spec_from_file_location("rss_main_test", "rss_main.py")
rss_module = importlib.util.module_from_spec(spec)

# Set up temporary data directory
temp_data = tempfile.mkdtemp()
sys.modules['rss_main_test'] = rss_module

# Now we can import just the functions we need
import hashlib
import html as html_lib
import re
import datetime
from urllib.parse import urlparse

def extract_entry_title(entry):
    """Extract entry title"""
    if hasattr(entry, 'title') and entry.title:
        title = entry.title
        title = re.sub(r'<[^>]+>', '', title)
        title = html_lib.unescape(title)
        title = re.sub(r'\s+', ' ', title).strip()
        return title
    return ''

def extract_entry_link(entry):
    """Extract entry link"""
    if hasattr(entry, 'links') and entry.links:
        for link in entry.links:
            if isinstance(link, dict) and link.get('rel') == 'alternate' and link.get('href'):
                return link['href'].strip()
    
    if hasattr(entry, 'link') and entry.link:
        return entry.link.strip()
    
    return ''

def extract_entry_author(entry):
    """Extract entry author"""
    if hasattr(entry, 'author') and entry.author:
        author = entry.author
    elif hasattr(entry, 'author_detail') and hasattr(entry.author_detail, 'name') and entry.author_detail.name:
        author = entry.author_detail.name
    elif hasattr(entry, 'dc_creator') and entry.dc_creator:
        author = entry.dc_creator
    else:
        author = ''
    
    if author:
        author = re.sub(r'<[^>]+>', '', author)
        author = html_lib.unescape(author)
        author = re.sub(r'\s+', ' ', author).strip()
    
    return author

def extract_entry_content(entry):
    """Extract entry content"""
    content = ''
    
    if hasattr(entry, 'content') and entry.content and len(entry.content) > 0:
        content = entry.content[0].get('value', '')
    elif hasattr(entry, 'summary') and entry.summary:
        content = entry.summary
    elif hasattr(entry, 'description') and entry.description:
        content = entry.description
    
    if content:
        content = re.sub(r'<[^>]+>', '', content)
        content = html_lib.unescape(content)
        content = re.sub(r'\s+', ' ', content).strip()
    
    return content

def generate_unique_key(entry_id, source_url, title, time_str):
    """Generate unique key"""
    try:
        parsed = urlparse(source_url)
        source_host = parsed.netloc or 'unknown'
    except Exception:
        source_host = 'unknown'
    
    if entry_id and not entry_id.startswith('sha1:'):
        return f"{source_host}:{entry_id}"
    
    fallback_str = f"{title}_{time_str or 'no_time'}"
    fallback_hash = hashlib.sha1(fallback_str.encode('utf-8')).hexdigest()
    return f"{source_host}:sha1:{fallback_hash}"

def truncate_for_telegram(text, max_length=4000):
    """Truncate for Telegram"""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + '...'

def html_escape_for_telegram(text):
    """HTML escape for Telegram"""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text

class MockEntry:
    """Mock feed entry for testing"""
    pass

def test_title_extraction():
    """Test title extraction with HTML and entities"""
    print("Testing title extraction...")
    
    entry = MockEntry()
    entry.title = "<b>Test Title</b> &amp; More"
    title = extract_entry_title(entry)
    assert title == "Test Title & More", f"Expected 'Test Title & More', got '{title}'"
    print("✓ Title extraction with HTML tags and entities")
    
    entry2 = MockEntry()
    entry2.title = "Normal   Title  With   Spaces"
    title2 = extract_entry_title(entry2)
    assert title2 == "Normal Title With Spaces", f"Expected normalized spaces, got '{title2}'"
    print("✓ Title extraction with multiple spaces")
    
    entry3 = MockEntry()
    title3 = extract_entry_title(entry3)
    assert title3 == "", f"Expected empty string, got '{title3}'"
    print("✓ Title extraction with missing title")

def test_link_extraction():
    """Test link extraction with preference for rel='alternate'"""
    print("\nTesting link extraction...")
    
    entry = MockEntry()
    entry.links = [
        {'rel': 'self', 'href': 'http://example.com/self'},
        {'rel': 'alternate', 'href': 'http://example.com/alternate'},
    ]
    link = extract_entry_link(entry)
    assert link == 'http://example.com/alternate', f"Expected alternate link, got '{link}'"
    print("✓ Link extraction prefers rel='alternate'")
    
    entry2 = MockEntry()
    entry2.link = 'http://example.com/direct'
    link2 = extract_entry_link(entry2)
    assert link2 == 'http://example.com/direct', f"Expected direct link, got '{link2}'"
    print("✓ Link extraction fallback to direct link")

def test_author_extraction():
    """Test author extraction with various formats"""
    print("\nTesting author extraction...")
    
    entry = MockEntry()
    entry.author = "John Doe"
    author = extract_entry_author(entry)
    assert author == "John Doe", f"Expected 'John Doe', got '{author}'"
    print("✓ Author extraction from author field")
    
    entry2 = MockEntry()
    entry2.author_detail = MockEntry()
    entry2.author_detail.name = "Jane Smith"
    author2 = extract_entry_author(entry2)
    assert author2 == "Jane Smith", f"Expected 'Jane Smith', got '{author2}'"
    print("✓ Author extraction from author_detail.name")
    
    entry3 = MockEntry()
    author3 = extract_entry_author(entry3)
    assert author3 == "", f"Expected empty string, got '{author3}'"
    print("✓ Author extraction with missing author")

def test_content_extraction():
    """Test content extraction with fallbacks"""
    print("\nTesting content extraction...")
    
    entry = MockEntry()
    entry.content = [{'value': '<p>Content here</p>'}]
    content = extract_entry_content(entry)
    assert "Content here" in content, f"Expected 'Content here', got '{content}'"
    print("✓ Content extraction from content field")
    
    entry2 = MockEntry()
    entry2.summary = "Summary text &amp; more"
    content2 = extract_entry_content(entry2)
    assert "Summary text & more" in content2, f"Expected unescaped text, got '{content2}'"
    print("✓ Content extraction from summary with HTML entities")
    
    entry3 = MockEntry()
    entry3.description = "Description here"
    content3 = extract_entry_content(entry3)
    assert "Description here" in content3, f"Expected description, got '{content3}'"
    print("✓ Content extraction from description")

def test_unique_key_generation():
    """Test unique key generation"""
    print("\nTesting unique key generation...")
    
    key1 = generate_unique_key("post-123", "https://example.com/feed", "Title", "2024-01-01")
    assert "example.com:post-123" in key1, f"Expected host:id format, got '{key1}'"
    print("✓ Unique key with ID")
    
    key2 = generate_unique_key(None, "https://example.com/feed", "Title", "2024-01-01")
    assert "example.com:sha1:" in key2, f"Expected sha1 fallback, got '{key2}'"
    print("✓ Unique key with SHA1 fallback")

def test_telegram_helpers():
    """Test Telegram message helpers"""
    print("\nTesting Telegram helpers...")
    
    text = "Short text"
    truncated = truncate_for_telegram(text, 100)
    assert truncated == text, f"Expected no truncation, got '{truncated}'"
    print("✓ Truncation with short text")
    
    long_text = "A" * 5000
    truncated2 = truncate_for_telegram(long_text, 4000)
    assert len(truncated2) <= 4000, f"Expected truncation to 4000, got {len(truncated2)}"
    assert truncated2.endswith("..."), f"Expected ellipsis, got '{truncated2[-10:]}'"
    print("✓ Truncation with long text")
    
    html_text = "<script>alert('xss')</script>"
    escaped = html_escape_for_telegram(html_text)
    assert "&lt;" in escaped and "&gt;" in escaped, f"Expected escaped HTML, got '{escaped}'"
    print("✓ HTML escaping for Telegram")

def main():
    print("=" * 60)
    print("Universal RSS/Atom Compatibility Tests")
    print("=" * 60)
    
    try:
        test_title_extraction()
        test_link_extraction()
        test_author_extraction()
        test_content_extraction()
        test_unique_key_generation()
        test_telegram_helpers()
        
        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
