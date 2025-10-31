#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Test script to demonstrate the debounce window bug fix

This script demonstrates that after the debounce window expires,
entries can be re-sent, preventing the bug where messages were
never re-sent after being seen once.
"""

import time
from unittest.mock import Mock
from dedup import generate_dedup_key, DedupHistory


def test_debounce_fix():
    """Test that entries can be re-sent after debounce window expires"""
    print("\n" + "="*70)
    print("DEBOUNCE WINDOW BUG FIX DEMONSTRATION")
    print("="*70)
    
    print("\nScenario: RSS entry should be re-sent after 24 hours")
    print("-" * 70)
    
    # Create history with 24-hour debounce
    hist = DedupHistory(max_size=1000, debounce_hours=24)
    current_time = time.time()
    
    # Create a mock RSS entry
    entry = Mock()
    entry.id = "https://nodeseek.com/vps-deal-123"
    entry.link = "https://nodeseek.com/vps-deal-123"
    entry.title = "Great VPS Deal - 50% Off"
    entry.author = "John Doe"
    
    key, _ = generate_dedup_key(entry)
    
    # First notification at T=0
    print(f"\n[T=0h] First notification:")
    print(f"  Entry: {entry.title}")
    print(f"  Dedup key: {key}")
    
    is_dup, reason = hist.is_duplicate(key, current_time)
    print(f"  Is duplicate? {is_dup} ({reason})")
    
    if not is_dup:
        hist.mark_seen(key, current_time)
        print(f"  ✅ Notification sent")
    else:
        print(f"  ⏭️ Skipped (unexpected!)")
        return False
    
    # Try to send again 1 hour later (should be blocked)
    time_1h = current_time + (1 * 3600)
    print(f"\n[T=1h] Same entry appears in feed again:")
    is_dup, reason = hist.is_duplicate(key, time_1h)
    print(f"  Is duplicate? {is_dup} ({reason})")
    
    if is_dup:
        print(f"  ⏭️ Correctly skipped (within 24h debounce window)")
    else:
        print(f"  ❌ ERROR: Should have been blocked!")
        return False
    
    # Try to send again 23 hours later (should still be blocked)
    time_23h = current_time + (23 * 3600)
    print(f"\n[T=23h] Same entry appears in feed again:")
    is_dup, reason = hist.is_duplicate(key, time_23h)
    print(f"  Is duplicate? {is_dup} ({reason})")
    
    if is_dup:
        print(f"  ⏭️ Correctly skipped (still within 24h debounce window)")
    else:
        print(f"  ❌ ERROR: Should have been blocked!")
        return False
    
    # Try to send again 25 hours later (should be ALLOWED - this is the fix!)
    time_25h = current_time + (25 * 3600)
    print(f"\n[T=25h] Same entry appears in feed again:")
    is_dup, reason = hist.is_duplicate(key, time_25h)
    print(f"  Is duplicate? {is_dup} ({reason})")
    
    if not is_dup:
        hist.mark_seen(key, time_25h)
        print(f"  ✅ Notification sent again (debounce window expired)")
        print(f"  🎉 BUG FIX VERIFIED: Entry can be re-sent after 24 hours!")
    else:
        print(f"  ❌ ERROR: Should have been allowed (bug still exists)!")
        return False
    
    # Try to send again 26 hours later (should be blocked, just sent at 25h)
    time_26h = current_time + (26 * 3600)
    print(f"\n[T=26h] Same entry appears in feed again:")
    is_dup, reason = hist.is_duplicate(key, time_26h)
    print(f"  Is duplicate? {is_dup} ({reason})")
    
    if is_dup:
        print(f"  ⏭️ Correctly skipped (recently sent at T=25h)")
    else:
        print(f"  ❌ ERROR: Should have been blocked!")
        return False
    
    print("\n" + "="*70)
    print("✅ DEBOUNCE FIX VERIFIED SUCCESSFULLY!")
    print("="*70)
    print("\nSummary:")
    print("  • T=0h:  Sent (first time)")
    print("  • T=1h:  Blocked (within 24h window)")
    print("  • T=23h: Blocked (within 24h window)")
    print("  • T=25h: Sent (window expired) ← BUG FIX!")
    print("  • T=26h: Blocked (recently sent)")
    print("\nBefore fix: Entries would NEVER be re-sent after first notification")
    print("After fix:  Entries CAN be re-sent after debounce window expires")
    
    return True


def test_cleanup_removes_expired():
    """Test that cleanup removes expired entries to save memory"""
    print("\n" + "="*70)
    print("CLEANUP OF EXPIRED ENTRIES")
    print("="*70)
    
    hist = DedupHistory(max_size=1000, debounce_hours=24)
    current_time = time.time()
    
    # Add entries at different times
    hist.mark_seen("recent-1", current_time)
    hist.mark_seen("recent-2", current_time - (1 * 3600))  # 1h ago
    hist.mark_seen("old-1", current_time - (25 * 3600))    # 25h ago
    hist.mark_seen("old-2", current_time - (48 * 3600))    # 48h ago
    hist.mark_seen("old-3", current_time - (72 * 3600))    # 72h ago
    
    print(f"\nBefore cleanup:")
    print(f"  Total entries: {hist.size()}")
    
    # Cleanup
    hist.cleanup_old_entries(current_time)
    
    print(f"\nAfter cleanup (remove entries > 24h old):")
    print(f"  Total entries: {hist.size()}")
    
    # Check which entries remain
    is_recent_1 = hist.is_duplicate("recent-1", current_time)[0]
    is_recent_2 = hist.is_duplicate("recent-2", current_time)[0]
    is_old_1 = hist.is_duplicate("old-1", current_time)[0]
    is_old_2 = hist.is_duplicate("old-2", current_time)[0]
    
    print(f"\n  recent-1 (0h old):  in history? {is_recent_1} ✓")
    print(f"  recent-2 (1h old):  in history? {is_recent_2} ✓")
    print(f"  old-1 (25h old):    in history? {is_old_1} (removed)")
    print(f"  old-2 (48h old):    in history? {is_old_2} (removed)")
    
    if hist.size() == 2 and is_recent_1 and is_recent_2 and not is_old_1 and not is_old_2:
        print("\n✅ Cleanup working correctly!")
        print("   Old entries removed, recent entries preserved")
        return True
    else:
        print("\n❌ Cleanup not working as expected")
        return False


def main():
    print("\n" + "#"*70)
    print("# RSS DEDUPLICATION BUG FIX VERIFICATION")
    print("#"*70)
    print("\nThis script verifies the fix for the bug where RSS entries")
    print("were never re-sent after being seen once, even after 24 hours.")
    
    success = True
    
    # Test 1: Debounce fix
    if not test_debounce_fix():
        success = False
    
    # Test 2: Cleanup
    if not test_cleanup_removes_expired():
        success = False
    
    print("\n" + "#"*70)
    if success:
        print("# ✅ ALL VERIFICATION TESTS PASSED!")
    else:
        print("# ❌ SOME TESTS FAILED")
    print("#"*70 + "\n")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
