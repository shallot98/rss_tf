#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RSS Feed Deduplication Module

Provides stable deduplication keys for RSS feed entries with:
- Priority-based unique ID extraction (entry.id > entry.guid > normalized link)
- URL normalization (lowercase, tracking param removal, query param sorting)
- Author-based differentiation for aggregator feeds
- Time-based debounce window
- Atomic persistence with corruption recovery
"""

import re
import time
import logging
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from typing import Dict, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)

# Tracking parameters to strip from URLs
TRACKING_PARAMS = {
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'fbclid', 'gclid', 'msclkid', 'mc_cid', 'mc_eid',
    '_ga', '_gac', '_gl', '_ke',
    'ref', 'referrer', 'source',
    'share', 'share_from', 'share_id'
}


def normalize_url(url: str) -> str:
    """
    Normalize a URL for deduplication by:
    - Converting scheme and netloc to lowercase
    - Removing tracking parameters
    - Sorting remaining query parameters
    - Removing fragments
    - Removing trailing slashes from path
    
    Args:
        url: The URL to normalize
        
    Returns:
        Normalized URL string
    """
    if not url:
        return ''
    
    try:
        parsed = urlparse(url.strip())
        
        # Lowercase scheme and netloc
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path.rstrip('/')
        
        # Parse and filter query parameters
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        filtered_params = {
            k: v for k, v in query_params.items()
            if k.lower() not in TRACKING_PARAMS
        }
        
        # Sort parameters for consistency
        sorted_query = urlencode(sorted(filtered_params.items()), doseq=True)
        
        # Rebuild URL without fragment
        normalized = urlunparse((scheme, netloc, path, '', sorted_query, ''))
        
        return normalized
    except Exception as e:
        logger.warning(f"URL normalization failed for '{url}': {e}")
        return url.lower().strip()


def normalize_author(author: str) -> str:
    """
    Normalize author name by:
    - Removing HTML tags
    - Removing extra whitespace
    - Removing special characters
    - Converting to lowercase
    
    Args:
        author: The author name to normalize
        
    Returns:
        Normalized author string
    """
    if not author:
        return 'unknown'
    
    # Remove HTML tags
    author = re.sub(r'<[^>]+>', '', author)
    # Remove extra whitespace (including unicode spaces)
    author = re.sub(r'[\s\u3000\u00A0]+', '', author)
    # Remove special characters, keep alphanumeric and CJK
    author = re.sub(r'[^\w\u4e00-\u9fff]', '', author)
    # Lowercase
    author = author.lower().strip()
    
    return author if author else 'unknown'


def extract_entry_id(entry) -> Optional[str]:
    """
    Extract a stable ID from a feedparser entry using priority:
    1. entry.id (RSS/Atom standard field)
    2. entry.guid (RSS guid field)
    3. None if neither available
    
    Args:
        entry: feedparser entry object
        
    Returns:
        Entry ID string or None
    """
    # Priority 1: entry.id
    if hasattr(entry, 'id') and entry.id:
        entry_id = str(entry.id).strip()
        if entry_id:
            logger.debug(f"Using entry.id: {entry_id}")
            return entry_id
    
    # Priority 2: entry.guid
    if hasattr(entry, 'guid') and entry.guid:
        guid = str(entry.guid).strip()
        if guid:
            logger.debug(f"Using entry.guid: {guid}")
            return guid
    
    return None


def generate_dedup_key(entry, fallback_to_link: bool = True) -> Tuple[str, Dict[str, str]]:
    """
    Generate a stable deduplication key for an RSS feed entry.
    
    Strategy:
    - Primary: Use entry.id or entry.guid if available
    - Fallback: Use normalized link + author combination
    - Author is always included to avoid collisions on aggregator sites
    
    Args:
        entry: feedparser entry object
        fallback_to_link: If True, fall back to link-based key when no ID available
        
    Returns:
        Tuple of (dedup_key, debug_info_dict)
    """
    debug_info = {}
    
    # Extract author
    author = ''
    if hasattr(entry, 'author') and entry.author:
        author = entry.author
    elif hasattr(entry, 'author_detail') and entry.author_detail:
        author = entry.author_detail.get('name', '')
    elif hasattr(entry, 'dc_creator') and entry.dc_creator:
        author = entry.dc_creator
    
    author_norm = normalize_author(author)
    debug_info['author_raw'] = author
    debug_info['author_normalized'] = author_norm
    
    # Try to get stable entry ID
    entry_id = extract_entry_id(entry)
    
    if entry_id:
        # Use entry ID as primary key, combined with author
        dedup_key = f"id:{entry_id}:author:{author_norm}"
        debug_info['key_type'] = 'entry_id'
        debug_info['entry_id'] = entry_id
    elif fallback_to_link and hasattr(entry, 'link') and entry.link:
        # Fallback to normalized link
        raw_link = entry.link
        normalized_link = normalize_url(raw_link)
        debug_info['key_type'] = 'link'
        debug_info['link_raw'] = raw_link
        debug_info['link_normalized'] = normalized_link
        
        # Create hash from normalized link for shorter key
        import hashlib
        link_hash = hashlib.sha256(normalized_link.encode()).hexdigest()[:16]
        dedup_key = f"link:{link_hash}:author:{author_norm}"
    else:
        # No usable identifier
        debug_info['key_type'] = 'none'
        dedup_key = None
    
    debug_info['dedup_key'] = dedup_key
    
    return dedup_key, debug_info


class DedupHistory:
    """
    Manages deduplication history with timestamps and debounce window.
    
    Features:
    - Bounded history size (LRU-style)
    - Timestamp-based debounce window
    - Thread-safe operations (when used with external locking)
    """
    
    def __init__(self, max_size: int = 1000, debounce_hours: int = 24):
        """
        Initialize deduplication history.
        
        Args:
            max_size: Maximum number of keys to keep in history
            debounce_hours: Hours to suppress re-sends of same key
        """
        self.max_size = max_size
        self.debounce_seconds = debounce_hours * 3600
        # Dict mapping dedup_key -> timestamp
        self.history: Dict[str, float] = {}
    
    def is_duplicate(self, key: str, current_time: Optional[float] = None) -> Tuple[bool, str]:
        """
        Check if a key is a duplicate based on history and debounce window.
        
        Args:
            key: Deduplication key to check
            current_time: Current timestamp (defaults to time.time())
            
        Returns:
            Tuple of (is_duplicate, reason)
            - Returns (True, reason) if within debounce window (suppress re-send)
            - Returns (False, reason) if outside debounce window (allow re-send)
            - Returns (False, 'new') if not in history (allow send)
        """
        if current_time is None:
            current_time = time.time()
        
        if key not in self.history:
            return False, 'new'
        
        last_seen = self.history[key]
        time_elapsed = current_time - last_seen
        
        if time_elapsed < self.debounce_seconds:
            return True, f'debounced ({time_elapsed/3600:.1f}h ago)'
        else:
            # Outside debounce window - allow re-sending
            return False, f'expired ({time_elapsed/3600:.1f}h ago, outside {self.debounce_seconds/3600:.0f}h window)'
    
    def mark_seen(self, key: str, current_time: Optional[float] = None):
        """
        Mark a key as seen at the given time.
        
        Args:
            key: Deduplication key
            current_time: Timestamp (defaults to time.time())
        """
        if current_time is None:
            current_time = time.time()
        
        self.history[key] = current_time
        self._trim_history()
    
    def _trim_history(self):
        """
        Trim history to max_size by removing oldest entries.
        """
        if len(self.history) <= self.max_size:
            return
        
        # Sort by timestamp and keep newest max_size entries
        sorted_items = sorted(self.history.items(), key=lambda x: x[1], reverse=True)
        self.history = dict(sorted_items[:self.max_size])
        
        logger.debug(f"Trimmed dedup history to {len(self.history)} entries")
    
    def cleanup_old_entries(self, current_time: Optional[float] = None):
        """
        Remove entries older than debounce window to save memory.
        
        Args:
            current_time: Current timestamp (defaults to time.time())
        """
        if current_time is None:
            current_time = time.time()
        
        cutoff_time = current_time - self.debounce_seconds
        before_count = len(self.history)
        
        self.history = {
            k: v for k, v in self.history.items()
            if v >= cutoff_time
        }
        
        removed = before_count - len(self.history)
        if removed > 0:
            logger.debug(f"Cleaned up {removed} old entries from dedup history")
    
    def to_dict(self) -> Dict[str, float]:
        """
        Export history to a dictionary for serialization.
        
        Returns:
            Dictionary mapping keys to timestamps
        """
        return self.history.copy()
    
    def from_dict(self, data: Dict[str, float], current_time: Optional[float] = None):
        """
        Import history from a dictionary.
        
        Args:
            data: Dictionary mapping keys to timestamps
            current_time: Current timestamp for cleanup (defaults to time.time())
        """
        if current_time is None:
            current_time = time.time()
        
        # Only keep entries within debounce window
        cutoff_time = current_time - self.debounce_seconds
        self.history = {
            k: v for k, v in data.items()
            if isinstance(v, (int, float)) and v >= cutoff_time
        }
        
        self._trim_history()
        logger.info(f"Loaded {len(self.history)} entries into dedup history")
    
    def size(self) -> int:
        """Return current history size."""
        return len(self.history)
