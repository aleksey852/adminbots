"""
User Model - Typed representation of user data
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    """Represents a registered bot user"""
    id: int
    telegram_id: int
    username: str
    full_name: str
    phone: str
    is_blocked: bool = False
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_db_row(cls, row: dict) -> 'User':
        """Create User from database row"""
        return cls(
            id=row['id'],
            telegram_id=row['telegram_id'],
            username=row.get('username', ''),
            full_name=row.get('full_name', ''),
            phone=row.get('phone', ''),
            is_blocked=row.get('is_blocked', False),
            created_at=row.get('created_at'),
        )


@dataclass
class UserStats:
    """User statistics for profile display"""
    user: User
    receipts_count: int = 0
    tickets_count: int = 0
    promo_tickets: int = 0
    manual_tickets: int = 0
    
    @property
    def total_tickets(self) -> int:
        return self.tickets_count + self.promo_tickets + self.manual_tickets
