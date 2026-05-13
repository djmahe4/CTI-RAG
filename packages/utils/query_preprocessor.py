"""
Query Preprocessor - Extract metadata filter conditions from user queries
"""

import re
from datetime import datetime
from typing import Dict, Optional, Any, List
from ..utils import logger


class QueryPreprocessor:
    """Query Preprocessor - Extracts date information and generates date_key for filtering."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        
        # Month Name Mapping
        self.month_names = {
            'january': 1, 'february': 2, 'march': 3, 'april': 4,
            'may': 5, 'june': 6, 'july': 7, 'august': 8,
            'september': 9, 'october': 10, 'november': 11, 'december': 12,
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
            'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
            'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }

    def extract_metadata_filters(self, query: str) -> Dict[str, Any]:
        """Extract date_key filter conditions from the query (supports multiple dates)."""
        if not self.enabled:
            return {}
            
        filters = {}
        date_keys = self._extract_date_keys(query)
        if date_keys:
            filters['date_keys'] = date_keys
            logger.info(f"Extracted metadata filter conditions: {filters}")
        else:
            logger.debug(f"No date information found in query. Date filter disabled.")
        
        return filters

    def _extract_date_keys(self, query: str) -> List[str]:
        """Parse all dates from the query and return a list of 'YYYYMMDD' strings."""
        date_keys = []
        
        # Match YYYY-MM-DD formats (e.g., 2025-01-06)
        for match in re.finditer(r'(\d{4})-(\d{1,2})-(\d{1,2})', query):
            year, month, day = map(int, match.groups())
            date_key = f"{year:04d}{month:02d}{day:02d}"
            if date_key not in date_keys:
                date_keys.append(date_key)

        # Match Month Day, Year formats (e.g., January 6, 2025)
        month_pattern = r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})'
        for match in re.finditer(month_pattern, query, re.IGNORECASE):
            month_name, day_str, year_str = match.groups()
            year, day = int(year_str), int(day_str)
            month = self.month_names.get(month_name.lower())
            if month:
                date_key = f"{year:04d}{month:02d}{day:02d}"
                if date_key not in date_keys:
                    date_keys.append(date_key)
        
        # Match MM-DD formats (assuming current year, e.g., 01-06)
        for match in re.finditer(r'\b(\d{1,2})-(\d{1,2})\b', query):
            # Avoid matching parts of YYYY-MM-DD
            if match.start() > 0 and query[match.start()-1] == '-':
                continue
            month, day = map(int, match.groups())
            if 1 <= month <= 12 and 1 <= day <= 31:
                year = datetime.now().year
                date_key = f"{year:04d}{month:02d}{day:02d}"
                if date_key not in date_keys:
                    date_keys.append(date_key)
            
        return date_keys

    def build_milvus_filter(self, filters: Dict[str, Any]) -> Optional[str]:
        """Build Milvus date_key filter expression (supports OR logic for multiple dates)."""
        date_keys = filters.get('date_keys', [])
        if not date_keys:
            return None
        
        # Single date filter
        if len(date_keys) == 1:
            return f"date_key == '{date_keys[0]}'"
        
        # Multiple dates filter (OR)
        or_conditions = [f"date_key == '{dk}'" for dk in date_keys]
        return "(" + " or ".join(or_conditions) + ")"
