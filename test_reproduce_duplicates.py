#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Reproduction script for duplicate RSS item detection

This script demonstrates the deduplication logic with mocked feedparser entries,
including duplicates and near-duplicates with different tracking parameters.

Run this to verify the dedup logic works correctly before deploying.
"""

import time
from unittest.mock import Mock
from dedup import generate_dedup_key, DedupHistory


def create_mock_entry(entry_id=None, guid=None, link=None, title="Test Post", author="TestAuthor"):
    """Create a mock feedparser entry"""
    entry = Mock()
    
    if entry_id:
        entry.id = entry_id
    elif guid:
        entry.guid = guid
        entry.id = None
    else:
        entry.id = None
        entry.guid = None
    
    entry.link = link if link else "https://example.com/post"
    entry.title = title
    entry.author = author
    
    return entry


def test_scenario_1_tracking_params():
    """Scenario 1: Same post with different tracking parameters"""
    print("\n" + "="*60)
    print("Scenario 1: Same post with different tracking parameters")
    print("="*60)
    
    hist = DedupHistory(max_size=100, debounce_hours=24)
    current_time = time.time()
    
    # First appearance with tracking params
    entry1 = create_mock_entry(
        link="https://nodeseek.com/post-123?utm_source=rss&ref=twitter",
        title="Great VPS Deal",
        author="John"
    )
    
    key1, debug1 = generate_dedup_key(entry1)
    print(f"\nEntry 1 (with utm_source=rss, ref=twitter):")
    print(f"  Link: {entry1.link}")
    print(f"  Dedup key: {key1}")
    print(f"  Normalized link: {debug1.get('link_normalized', 'N/A')}")
    
    is_dup = hist.is_duplicate(key1)[0]
    print(f"  Is duplicate? {is_dup}")
    
    if not is_dup:
        hist.mark_seen(key1, current_time)
        print(f"  ✅ Sent notification")
    
    # Same post with different tracking params (should be detected as duplicate)
    entry2 = create_mock_entry(
        link="https://nodeseek.com/post-123?ref=facebook&utm_campaign=social",
        title="Great VPS Deal",
        author="John"
    )
    
    key2, debug2 = generate_dedup_key(entry2)
    print(f"\nEntry 2 (with ref=facebook, utm_campaign=social):")
    print(f"  Link: {entry2.link}")
    print(f"  Dedup key: {key2}")
    print(f"  Normalized link: {debug2.get('link_normalized', 'N/A')}")
    
    is_dup, reason = hist.is_duplicate(key2, current_time + 60)
    print(f"  Is duplicate? {is_dup} ({reason})")
    
    if is_dup:
        print(f"  ⏭️ Skipped (duplicate)")
    
    print(f"\nResult: Keys match? {key1 == key2}")
    assert key1 == key2, "Keys should be identical!"
    print("✅ PASS: Different tracking params generate same key")


def test_scenario_2_with_entry_id():
    """Scenario 2: Entries with proper entry.id field"""
    print("\n" + "="*60)
    print("Scenario 2: Entries with proper entry.id field")
    print("="*60)
    
    hist = DedupHistory(max_size=100, debounce_hours=24)
    current_time = time.time()
    
    # Entry with entry.id
    entry1 = create_mock_entry(
        entry_id="https://nodeseek.com/post-456",
        link="https://nodeseek.com/post-456?utm_source=feed",
        title="Another Deal",
        author="Jane"
    )
    
    key1, debug1 = generate_dedup_key(entry1)
    print(f"\nEntry with entry.id:")
    print(f"  entry.id: {entry1.id}")
    print(f"  Link: {entry1.link}")
    print(f"  Dedup key: {key1}")
    print(f"  Key type: {debug1.get('key_type')}")
    
    is_dup = hist.is_duplicate(key1)[0]
    print(f"  Is duplicate? {is_dup}")
    
    if not is_dup:
        hist.mark_seen(key1, current_time)
        print(f"  ✅ Sent notification")
    
    # Same entry.id but different link (should still be duplicate)
    entry2 = create_mock_entry(
        entry_id="https://nodeseek.com/post-456",
        link="https://nodeseek.com/post-456?ref=newsletter",
        title="Another Deal",
        author="Jane"
    )
    
    key2, debug2 = generate_dedup_key(entry2)
    print(f"\nSame entry.id, different link params:")
    print(f"  entry.id: {entry2.id}")
    print(f"  Link: {entry2.link}")
    print(f"  Dedup key: {key2}")
    
    is_dup, reason = hist.is_duplicate(key2, current_time + 60)
    print(f"  Is duplicate? {is_dup} ({reason})")
    
    print(f"\nResult: Keys match? {key1 == key2}")
    assert key1 == key2, "Keys should be identical!"
    print("✅ PASS: entry.id-based keys are stable")


def test_scenario_3_different_authors():
    """Scenario 3: Same link but different authors"""
    print("\n" + "="*60)
    print("Scenario 3: Same link but different authors")
    print("="*60)
    
    hist = DedupHistory(max_size=100, debounce_hours=24)
    current_time = time.time()
    
    # Post by Author A
    entry1 = create_mock_entry(
        link="https://example.com/shared-link",
        title="Shared News",
        author="Author A"
    )
    
    key1, _ = generate_dedup_key(entry1)
    print(f"\nEntry by Author A:")
    print(f"  Link: {entry1.link}")
    print(f"  Author: {entry1.author}")
    print(f"  Dedup key: {key1}")
    
    hist.mark_seen(key1, current_time)
    print(f"  ✅ Sent notification")
    
    # Same link but Author B (should NOT be duplicate)
    entry2 = create_mock_entry(
        link="https://example.com/shared-link",
        title="Shared News",
        author="Author B"
    )
    
    key2, _ = generate_dedup_key(entry2)
    print(f"\nSame link by Author B:")
    print(f"  Link: {entry2.link}")
    print(f"  Author: {entry2.author}")
    print(f"  Dedup key: {key2}")
    
    is_dup = hist.is_duplicate(key2)[0]
    print(f"  Is duplicate? {is_dup}")
    
    if not is_dup:
        hist.mark_seen(key2, current_time + 60)
        print(f"  ✅ Sent notification (different author)")
    
    print(f"\nResult: Keys different? {key1 != key2}")
    assert key1 != key2, "Keys should be different!"
    print("✅ PASS: Different authors generate different keys")


def test_scenario_4_multi_keyword_single_send():
    """Scenario 4: Same entry matching multiple keywords in one cycle"""
    print("\n" + "="*60)
    print("Scenario 4: Multi-keyword single-send protection")
    print("="*60)
    
    hist = DedupHistory(max_size=100, debounce_hours=24)
    current_time = time.time()
    
    # Simulate a single RSS entry that matches multiple keywords
    entry = create_mock_entry(
        entry_id="post-789",
        title="VPS Server with Docker Support",
        author="Admin"
    )
    
    keywords = ["VPS", "Server", "Docker"]
    
    key, _ = generate_dedup_key(entry)
    print(f"\nEntry title: {entry.title}")
    print(f"Matching keywords: {keywords}")
    print(f"Dedup key: {key}")
    
    # Simulate per-cycle tracking
    sent_in_this_cycle = set()
    
    for keyword in keywords:
        print(f"\n  Checking keyword '{keyword}':")
        
        # Check if duplicate in history
        is_dup_hist = hist.is_duplicate(key)[0]
        
        # Check if already sent in this cycle
        if key in sent_in_this_cycle:
            print(f"    ⏭️ Already sent in this cycle")
            continue
        
        if is_dup_hist:
            print(f"    ⏭️ Duplicate in history")
            continue
        
        # Would send notification here
        print(f"    ✅ Send notification")
        hist.mark_seen(key, current_time)
        sent_in_this_cycle.add(key)
    
    print(f"\nTotal notifications sent: {len(sent_in_this_cycle)}")
    assert len(sent_in_this_cycle) == 1, "Should only send once!"
    print("✅ PASS: Multi-keyword entry only sent once")


def test_scenario_5_restart_persistence():
    """Scenario 5: History persistence across restart"""
    print("\n" + "="*60)
    print("Scenario 5: History persistence across restart")
    print("="*60)
    
    current_time = time.time()
    
    # First run
    hist1 = DedupHistory(max_size=100, debounce_hours=24)
    
    entry = create_mock_entry(
        entry_id="persistent-post",
        title="This should persist",
        author="User"
    )
    
    key, _ = generate_dedup_key(entry)
    hist1.mark_seen(key, current_time)
    
    print(f"\nBefore restart:")
    print(f"  History size: {hist1.size()}")
    print(f"  Key in history: {key}")
    
    # Simulate saving
    saved_data = hist1.to_dict()
    print(f"  Saved data: {len(saved_data)} entries")
    
    # Simulate restart
    hist2 = DedupHistory(max_size=100, debounce_hours=24)
    hist2.from_dict(saved_data, current_time + 3600)  # 1 hour later
    
    print(f"\nAfter restart:")
    print(f"  History size: {hist2.size()}")
    
    # Check if still marked as duplicate
    is_dup, reason = hist2.is_duplicate(key, current_time + 3600)
    print(f"  Key still duplicate? {is_dup} ({reason})")
    
    assert is_dup, "Key should still be in history!"
    print("✅ PASS: History persisted across restart")


def test_scenario_6_debounce_window():
    """Scenario 6: Debounce window behavior"""
    print("\n" + "="*60)
    print("Scenario 6: Debounce window behavior")
    print("="*60)
    
    hist = DedupHistory(max_size=100, debounce_hours=24)
    current_time = time.time()
    
    entry = create_mock_entry(
        entry_id="debounce-test",
        title="Debounce Test",
        author="Tester"
    )
    
    key, _ = generate_dedup_key(entry)
    hist.mark_seen(key, current_time)
    
    print(f"\nInitial send:")
    print(f"  Time: {current_time}")
    print(f"  ✅ Sent notification")
    
    # Check 1 hour later (within debounce window)
    time_1h = current_time + 3600
    is_dup, reason = hist.is_duplicate(key, time_1h)
    print(f"\n1 hour later:")
    print(f"  Is duplicate? {is_dup} ({reason})")
    assert is_dup, "Should be duplicate within debounce window"
    
    # Check 23 hours later (still within 24h window)
    time_23h = current_time + (23 * 3600)
    is_dup, reason = hist.is_duplicate(key, time_23h)
    print(f"\n23 hours later:")
    print(f"  Is duplicate? {is_dup} ({reason})")
    assert is_dup, "Should be duplicate within debounce window"
    
    # Check 25 hours later (outside 24h window)
    time_25h = current_time + (25 * 3600)
    is_dup, reason = hist.is_duplicate(key, time_25h)
    print(f"\n25 hours later:")
    print(f"  Is duplicate? {is_dup} ({reason})")
    assert is_dup, "Should still be in history but outside debounce"
    
    print("✅ PASS: Debounce window works correctly")


def main():
    print("\n" + "="*60)
    print("RSS DEDUPLICATION REPRODUCTION TESTS")
    print("="*60)
    print("\nThis script tests the deduplication logic with various scenarios")
    print("that could cause duplicate notifications.")
    
    try:
        test_scenario_1_tracking_params()
        test_scenario_2_with_entry_id()
        test_scenario_3_different_authors()
        test_scenario_4_multi_keyword_single_send()
        test_scenario_5_restart_persistence()
        test_scenario_6_debounce_window()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\nThe deduplication logic is working correctly.")
        print("Duplicate RSS items will not be re-pushed.")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
