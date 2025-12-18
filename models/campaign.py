"""
Campaign Model - Typed representation of campaign data
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List


@dataclass
class Campaign:
    """Represents a campaign (broadcast, message, or raffle)"""
    id: int
    type: str  # 'broadcast', 'message', 'raffle'
    content: Dict[str, Any]
    bot_id: int
    scheduled_for: Optional[datetime] = None
    is_completed: bool = False
    sent_count: int = 0
    failed_count: int = 0
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: dict, bot_id: int = None) -> 'Campaign':
        """Create Campaign from database row"""
        return cls(
            id=row['id'],
            type=row['type'],
            content=row['content'] if isinstance(row['content'], dict) else {},
            bot_id=bot_id or row.get('_bot_id') or row.get('bot_id', 0),
            scheduled_for=row.get('scheduled_for'),
            is_completed=row.get('is_completed', False),
            sent_count=row.get('sent_count', 0),
            failed_count=row.get('failed_count', 0),
            created_at=row.get('created_at'),
        )


@dataclass
class CampaignProgress:
    """Tracks broadcast progress for resume capability"""
    campaign_id: int
    last_user_id: int = 0
    sent_count: int = 0
    failed_count: int = 0


@dataclass
class RaffleWinner:
    """Represents a raffle winner"""
    id: int
    campaign_id: int
    user_id: int
    telegram_id: int
    prize_name: str
    notified: bool = False
    full_name: Optional[str] = None
    username: Optional[str] = None
    created_at: Optional[datetime] = None
