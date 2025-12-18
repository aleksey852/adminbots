"""
Database module - exports for bot handlers and admin panel

Structure:
- db.py: Panel database connection pool and schema
- panel_db.py: Panel-specific operations (bot registry, panel users)  
- methods.py: Bot management operations (bots table, admins)
- bot_db.py: Per-bot database connections
- bot_methods.py: Bot-specific data operations (users, receipts, etc.)
"""
from database.db import init_db, close_db, get_connection

# Panel/Bot management methods (work with panel database)
from database.methods import (
    # Bot Management
    get_bot_by_token, get_active_bots, get_bot, get_bot_config, get_all_bots,
    # Bot Admins
    get_bot_admins, add_bot_admin, remove_bot_admin, is_bot_admin,
    update_bot_admins_array,
    # Bot Lifecycle
    get_bot_enabled_modules, update_bot_modules, archive_bot,
    # Health
    check_db_health,
    # Utils
    escape_like,
)

# Panel users (from panel_db)
from database.panel_db import (
    get_panel_user, get_panel_user_by_id, update_panel_user_login,
    get_all_panel_users, create_panel_user, update_panel_user, delete_panel_user,
)

# Bot-specific methods (work with per-bot databases via context)
from database.bot_methods import (
    # Context
    bot_db_context, set_current_bot_db, get_current_bot_db,
    # Users
    add_user, get_user, get_user_by_id,
    get_user_with_stats, update_username, get_total_users_count,
    get_user_ids_paginated, get_users_paginated, search_users, get_user_detail,
    get_user_receipts_detailed, block_user, update_user_fields,
    block_user_by_telegram_id,
    # Receipts
    add_receipt, is_receipt_exists, get_user_receipts, get_user_receipts_count,
    get_user_tickets_count, get_all_receipts_paginated, get_total_receipts_count,
    # Campaigns
    add_campaign, get_pending_campaigns, mark_campaign_completed,
    get_recent_campaigns,
    # Winners & Raffle
    get_raffle_participants, get_participants_count, get_participants_with_tickets,
    get_total_tickets_count, save_winners_atomic, add_winner,
    get_campaign_winners, get_recent_raffles_with_winners,
    get_all_winners_for_export, get_user_wins, get_raffle_losers,
    mark_winner_notified,
    # Broadcast
    get_broadcast_progress, save_broadcast_progress, delete_broadcast_progress,
    get_all_users_for_broadcast,
    # Stats
    get_stats, get_stats_by_days,
    # Settings & Messages
    get_setting, set_setting, get_message, set_message,
    get_all_settings, get_all_messages,
    # Promo
    add_promo_codes, get_promo_code, use_promo_code, get_promo_stats,
    get_promo_codes_paginated,
    # Manual Tickets
    add_manual_tickets, get_user_manual_tickets, get_user_total_tickets,
    get_all_tickets_for_final_raffle,
    # Jobs
    create_job, get_active_jobs, get_job,
)
