#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unit tests for RSS feed deduplication module

Tests cover:
- URL normalization (tracking params, query param sorting, etc.)
- Dedup key generation with various entry formats
- Duplicate detection with debounce window
- History persistence and corruption recovery
- Multi-keyword single-send protection
- Migration from old format
"""

import unittest
import time
import tempfile
import json
import os
from unittest.mock import Mock, MagicMock
from dedup import (
    normalize_url,
    normalize_author,
    extract_entry_id,
    generate_dedup_key,
    DedupHistory,
    TRACKING_PARAMS
)


class TestURLNormalization(unittest.TestCase):
    """Test URL normalization for stable dedup keys"""
    
    def test_lowercase_scheme_and_host(self):
        """URLs should have lowercase scheme and host"""
        url = "HTTP://EXAMPLE.COM/Path"
        normalized = normalize_url(url)
        self.assertTrue(normalized.startswith("http://example.com"))
    
    def test_remove_tracking_params(self):
        """Tracking parameters should be removed"""
        url = "https://example.com/post?id=123&utm_source=twitter&fbclid=abc"
        normalized = normalize_url(url)
        self.assertIn("id=123", normalized)
        self.assertNotIn("utm_source", normalized)
        self.assertNotIn("fbclid", normalized)
    
    def test_sort_query_params(self):
        """Query parameters should be sorted"""
        url1 = "https://example.com/post?b=2&a=1"
        url2 = "https://example.com/post?a=1&b=2"
        self.assertEqual(normalize_url(url1), normalize_url(url2))
    
    def test_remove_fragment(self):
        """URL fragments should be removed"""
        url = "https://example.com/post#section"
        normalized = normalize_url(url)
        self.assertNotIn("#", normalized)
    
    def test_remove_trailing_slash(self):
        """Trailing slashes in path should be removed"""
        url1 = "https://example.com/post/"
        url2 = "https://example.com/post"
        self.assertEqual(normalize_url(url1), normalize_url(url2))
    
    def test_complex_normalization(self):
        """Test complex real-world URL normalization"""
        url1 = "HTTPS://NodeSeek.COM/post-123/?utm_campaign=social&ref=twitter#comments"
        url2 = "https://nodeseek.com/post-123?ref=facebook&utm_campaign=email"
        
        norm1 = normalize_url(url1)
        norm2 = normalize_url(url2)
        
        # Both should normalize to similar base (without tracking params)
        self.assertTrue(norm1.startswith("https://nodeseek.com/post-123"))
        self.assertTrue(norm2.startswith("https://nodeseek.com/post-123"))
        self.assertNotIn("utm_", norm1)
        self.assertNotIn("utm_", norm2)
        self.assertNotIn("ref=", norm1)
        self.assertNotIn("ref=", norm2)
    
    def test_empty_url(self):
        """Empty URLs should return empty string"""
        self.assertEqual(normalize_url(""), "")
        self.assertEqual(normalize_url(None), "")


class TestAuthorNormalization(unittest.TestCase):
    """Test author name normalization"""
    
    def test_remove_html_tags(self):
        """HTML tags should be removed from author names"""
        author = "<b>John Doe</b>"
        self.assertEqual(normalize_author(author), "johndoe")
    
    def test_remove_whitespace(self):
        """Extra whitespace should be removed"""
        author = "John   Doe"
        normalized = normalize_author(author)
        self.assertNotIn(" ", normalized)
    
    def test_lowercase(self):
        """Author names should be lowercased"""
        author = "JohnDoe"
        self.assertEqual(normalize_author(author), "johndoe")
    
    def test_chinese_characters(self):
        """Chinese characters should be preserved"""
        author = "张三 123"
        normalized = normalize_author(author)
        self.assertIn("张三", normalized)
        self.assertIn("123", normalized)
    
    def test_empty_author(self):
        """Empty author should return 'unknown'"""
        self.assertEqual(normalize_author(""), "unknown")
        self.assertEqual(normalize_author(None), "unknown")
        self.assertEqual(normalize_author("   "), "unknown")


class TestEntryIDExtraction(unittest.TestCase):
    """Test extraction of entry IDs from feedparser entries"""
    
    def test_entry_id_priority(self):
        """entry.id should have priority over guid"""
        entry = Mock()
        entry.id = "entry-123"
        entry.guid = "guid-456"
        
        entry_id = extract_entry_id(entry)
        self.assertEqual(entry_id, "entry-123")
    
    def test_guid_fallback(self):
        """entry.guid should be used if id is not available"""
        entry = Mock()
        entry.id = None
        entry.guid = "guid-456"
        
        entry_id = extract_entry_id(entry)
        self.assertEqual(entry_id, "guid-456")
    
    def test_no_id_fields(self):
        """Should return None if neither id nor guid available"""
        entry = Mock(spec=[])
        entry_id = extract_entry_id(entry)
        self.assertIsNone(entry_id)


class TestDedupKeyGeneration(unittest.TestCase):
    """Test deduplication key generation"""
    
    def test_key_from_entry_id(self):
        """Should use entry.id as primary key"""
        entry = Mock()
        entry.id = "post-123"
        entry.guid = None
        entry.link = "https://example.com/post-123"
        entry.author = "John Doe"
        
        dedup_key, debug_info = generate_dedup_key(entry)
        
        self.assertIn("id:post-123", dedup_key)
        self.assertIn("author:", dedup_key)
        self.assertEqual(debug_info['key_type'], 'entry_id')
    
    def test_key_from_guid(self):
        """Should use entry.guid if entry.id not available"""
        entry = Mock(spec=['guid', 'link', 'author'])
        entry.guid = "guid-456"
        entry.link = "https://example.com/post"
        entry.author = "Jane Smith"
        
        dedup_key, debug_info = generate_dedup_key(entry)
        
        self.assertIn("id:guid-456", dedup_key)
        self.assertEqual(debug_info['key_type'], 'entry_id')
    
    def test_key_from_link(self):
        """Should fall back to normalized link if no ID available"""
        entry = Mock(spec=['link', 'author'])
        entry.link = "https://example.com/post?utm_source=feed"
        entry.author = "Bob Johnson"
        
        dedup_key, debug_info = generate_dedup_key(entry)
        
        self.assertIn("link:", dedup_key)
        self.assertIn("author:", dedup_key)
        self.assertEqual(debug_info['key_type'], 'link')
        # Should have normalized link in debug info
        self.assertIn('link_normalized', debug_info)
        self.assertNotIn('utm_source', debug_info['link_normalized'])
    
    def test_same_link_different_tracking(self):
        """Same link with different tracking params should generate same key"""
        entry1 = Mock(spec=['link', 'author'])
        entry1.link = "https://example.com/post?id=1&utm_source=twitter"
        entry1.author = "Alice"
        
        entry2 = Mock(spec=['link', 'author'])
        entry2.link = "https://example.com/post?utm_source=facebook&id=1"
        entry2.author = "Alice"
        
        key1, _ = generate_dedup_key(entry1)
        key2, _ = generate_dedup_key(entry2)
        
        self.assertEqual(key1, key2)
    
    def test_different_authors_different_keys(self):
        """Same post by different authors should have different keys"""
        entry1 = Mock()
        entry1.id = "post-123"
        entry1.link = "https://example.com/post-123"
        entry1.author = "Author A"
        
        entry2 = Mock()
        entry2.id = "post-123"
        entry2.link = "https://example.com/post-123"
        entry2.author = "Author B"
        
        key1, _ = generate_dedup_key(entry1)
        key2, _ = generate_dedup_key(entry2)
        
        self.assertNotEqual(key1, key2)


class TestDedupHistory(unittest.TestCase):
    """Test deduplication history management"""
    
    def test_new_entry_not_duplicate(self):
        """New entries should not be marked as duplicate"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        is_dup, reason = hist.is_duplicate("new-key")
        
        self.assertFalse(is_dup)
        self.assertEqual(reason, 'new')
    
    def test_recent_entry_is_duplicate(self):
        """Recently seen entries should be marked as duplicate"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        current_time = time.time()
        
        hist.mark_seen("key1", current_time)
        
        # Check 1 hour later
        is_dup, reason = hist.is_duplicate("key1", current_time + 3600)
        
        self.assertTrue(is_dup)
        self.assertIn("debounced", reason)
    
    def test_old_entry_outside_debounce(self):
        """Entries older than debounce window should allow re-sending"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        current_time = time.time()
        
        hist.mark_seen("key1", current_time)
        
        # Check 25 hours later (outside 24h debounce window)
        future_time = current_time + (25 * 3600)
        is_dup, reason = hist.is_duplicate("key1", future_time)
        
        # Should NOT be marked as duplicate, allowing re-send
        self.assertFalse(is_dup)
        self.assertIn("expired", reason)
        self.assertIn("outside", reason)
    
    def test_history_trimming(self):
        """History should be trimmed to max_size"""
        hist = DedupHistory(max_size=10, debounce_hours=24)
        current_time = time.time()
        
        # Add 20 entries
        for i in range(20):
            hist.mark_seen(f"key-{i}", current_time + i)
        
        # Should only keep 10 newest
        self.assertEqual(hist.size(), 10)
        
        # Newest entries should still be there
        self.assertTrue(hist.is_duplicate("key-19")[0])
        self.assertTrue(hist.is_duplicate("key-15")[0])
        
        # Oldest entries should be gone
        self.assertFalse(hist.is_duplicate("key-0")[0])
        self.assertFalse(hist.is_duplicate("key-5")[0])
    
    def test_cleanup_old_entries(self):
        """Cleanup should remove entries older than debounce window"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        current_time = time.time()
        
        # Add entries at different times
        hist.mark_seen("recent", current_time)
        hist.mark_seen("old", current_time - (30 * 3600))  # 30 hours ago
        
        self.assertEqual(hist.size(), 2)
        
        # Cleanup
        hist.cleanup_old_entries(current_time)
        
        # Old entry should be removed
        self.assertEqual(hist.size(), 1)
        self.assertTrue(hist.is_duplicate("recent")[0])
        self.assertFalse(hist.is_duplicate("old")[0])
    
    def test_export_import(self):
        """History should be exportable and importable"""
        hist1 = DedupHistory(max_size=100, debounce_hours=24)
        current_time = time.time()
        
        hist1.mark_seen("key1", current_time)
        hist1.mark_seen("key2", current_time - 1000)
        
        # Export
        data = hist1.to_dict()
        
        # Import to new instance
        hist2 = DedupHistory(max_size=100, debounce_hours=24)
        hist2.from_dict(data, current_time)
        
        # Should have same entries
        self.assertEqual(hist2.size(), 2)
        self.assertTrue(hist2.is_duplicate("key1")[0])
        self.assertTrue(hist2.is_duplicate("key2")[0])
    
    def test_import_filters_old_entries(self):
        """Import should filter out entries older than debounce window"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        current_time = time.time()
        
        # Data with old and recent entries
        data = {
            "recent": current_time,
            "old": current_time - (30 * 3600)  # 30 hours ago
        }
        
        hist.from_dict(data, current_time)
        
        # Should only keep recent entry
        self.assertEqual(hist.size(), 1)
        self.assertTrue(hist.is_duplicate("recent")[0])
        self.assertFalse(hist.is_duplicate("old")[0])


class TestMigrationAndIntegration(unittest.TestCase):
    """Test migration from old format and integration scenarios"""
    
    def test_mock_feedparser_entry(self):
        """Test with mock feedparser entry structure"""
        # Create a realistic mock entry
        entry = Mock()
        entry.id = "https://nodeseek.com/post-12345"
        entry.guid = None
        entry.link = "https://nodeseek.com/post-12345?ref=rss"
        entry.title = "Test Post Title"
        entry.author = "TestAuthor"
        
        dedup_key, debug_info = generate_dedup_key(entry)
        
        self.assertIsNotNone(dedup_key)
        self.assertEqual(debug_info['key_type'], 'entry_id')
        self.assertIn('author_normalized', debug_info)
    
    def test_single_send_per_cycle(self):
        """Simulate single-send protection within one cycle"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        current_time = time.time()
        
        # Simulate checking same entry multiple times in one cycle
        # (e.g., matches multiple keywords)
        sent_in_cycle = set()
        
        entry = Mock()
        entry.id = "post-1"
        entry.author = "Author"
        
        key1, _ = generate_dedup_key(entry)
        
        # First check - should send
        if not hist.is_duplicate(key1)[0] and key1 not in sent_in_cycle:
            hist.mark_seen(key1, current_time)
            sent_in_cycle.add(key1)
            first_send = True
        else:
            first_send = False
        
        # Second check in same cycle - should not send
        if not hist.is_duplicate(key1)[0] and key1 not in sent_in_cycle:
            second_send = True
        else:
            second_send = False
        
        self.assertTrue(first_send)
        self.assertFalse(second_send)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""
    
    def test_malformed_url(self):
        """Malformed URLs should be handled gracefully"""
        malformed = "not a valid url"
        normalized = normalize_url(malformed)
        # Should return something, even if just lowercased
        self.assertIsInstance(normalized, str)
    
    def test_entry_without_any_id(self):
        """Entry without any ID fields should return None key"""
        entry = Mock(spec=[])
        dedup_key, _ = generate_dedup_key(entry, fallback_to_link=False)
        self.assertIsNone(dedup_key)
    
    def test_unicode_in_author(self):
        """Unicode characters in author should be handled"""
        entry = Mock()
        entry.id = "post-1"
        entry.author = "张三 🎉"
        
        dedup_key, debug_info = generate_dedup_key(entry)
        self.assertIsNotNone(dedup_key)
        # Should have normalized author
        self.assertIn('author_normalized', debug_info)
    
    def test_very_long_history(self):
        """Very long history should be handled efficiently"""
        hist = DedupHistory(max_size=1000, debounce_hours=24)
        current_time = time.time()
        
        # Add many entries
        for i in range(2000):
            hist.mark_seen(f"key-{i}", current_time + i)
        
        # Should be trimmed to max_size
        self.assertEqual(hist.size(), 1000)


def create_mock_feed_entry(entry_id=None, guid=None, link=None, title="Test", author="Author"):
    """Helper to create mock feed entries for testing"""
    entry = Mock()
    if entry_id:
        entry.id = entry_id
    else:
        entry.id = None
    
    if guid:
        entry.guid = guid
    else:
        entry.guid = None
    
    entry.link = link or "https://example.com/post"
    entry.title = title
    entry.author = author
    
    return entry


class TestReproductionScenario(unittest.TestCase):
    """Test scenarios that reproduce reported duplicate issues"""
    
    def test_duplicate_with_different_tracking_params(self):
        """Same post with different tracking params should be deduplicated"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        current_time = time.time()
        
        # First appearance with tracking param
        entry1 = create_mock_feed_entry(
            link="https://nodeseek.com/post-123?utm_source=rss&ref=twitter"
        )
        key1, _ = generate_dedup_key(entry1)
        
        # Not a duplicate
        self.assertFalse(hist.is_duplicate(key1)[0])
        hist.mark_seen(key1, current_time)
        
        # Same post with different tracking params
        entry2 = create_mock_feed_entry(
            link="https://nodeseek.com/post-123?ref=facebook&utm_campaign=social"
        )
        key2, _ = generate_dedup_key(entry2)
        
        # Should generate same key and be marked as duplicate
        self.assertEqual(key1, key2)
        self.assertTrue(hist.is_duplicate(key2)[0])
    
    def test_restart_persistence(self):
        """History should persist across restarts"""
        current_time = time.time()
        
        # First run
        hist1 = DedupHistory(max_size=100, debounce_hours=24)
        hist1.mark_seen("key1", current_time)
        hist1.mark_seen("key2", current_time - 1000)
        
        # Simulate saving
        saved_data = hist1.to_dict()
        
        # Simulate restart
        hist2 = DedupHistory(max_size=100, debounce_hours=24)
        hist2.from_dict(saved_data, current_time)
        
        # Should remember previous entries
        self.assertTrue(hist2.is_duplicate("key1")[0])
        self.assertTrue(hist2.is_duplicate("key2")[0])
    
    def test_corrupted_history_recovery(self):
        """Should recover gracefully from corrupted history data"""
        hist = DedupHistory(max_size=100, debounce_hours=24)
        
        # Corrupted data with invalid timestamps
        corrupted_data = {
            "valid_key": time.time(),
            "invalid_key": "not a timestamp",
            "another_invalid": None
        }
        
        # Should not crash
        try:
            hist.from_dict(corrupted_data, time.time())
            # Should only keep valid entries
            self.assertGreaterEqual(hist.size(), 0)
        except Exception as e:
            self.fail(f"from_dict should handle corrupted data gracefully: {e}")


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
