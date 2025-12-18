from database.db import init_db, close_db, get_connection
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
    # Panel users
    get_panel_user, get_panel_user_by_id, update_panel_user_login,
    get_all_panel_users, create_panel_user, update_panel_user, delete_panel_user,
)
# Re-export bot methods
from database.bot_methods import (
    # Users
    add_user, get_user, get_user_by_id,
    get_user_with_stats, update_username, get_total_users_count, 
    get_user_ids_paginated, get_users_paginated, search_users, get_user_detail,
    get_user_receipts_detailed, block_user, update_user_fields,
    # Receipts
    add_receipt, is_receipt_exists, get_user_receipts, get_user_receipts_count,
    get_user_tickets_count, get_all_receipts_paginated, get_total_receipts_count,
    # Campaigns
    add_campaign, get_pending_campaigns, mark_campaign_completed, 
    get_recent_campaigns,
    # Winners
    get_participants_count, get_participants_with_tickets,
    get_total_tickets_count, save_winners_atomic,
    get_campaign_winners, get_recent_raffles_with_winners, 
    get_all_winners_for_export, get_user_wins, get_raffle_losers,
    mark_winner_notified,
    # Broadcast
    get_broadcast_progress, save_broadcast_progress, delete_broadcast_progress,
    # Stats
    get_stats, get_stats_by_days,
    # Promo
    add_promo_codes, get_promo_code, use_promo_code, get_promo_stats, 
    # Manual
    add_manual_tickets, get_user_manual_tickets, get_user_total_tickets,
    get_all_tickets_for_final_raffle,
    # Jobs
    create_job, get_active_jobs, get_job
)

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
    # Panel users
    get_panel_user, get_panel_user_by_id, update_panel_user_login,
    get_all_panel_users, create_panel_user, update_panel_user, delete_panel_user,
)
# Re-export bot methods (without needing bot_id)
from database.bot_methods import (
    # Users
    add_user, get_user, get_user_by_id,
    get_user_with_stats, update_username, get_total_users_count, 
    get_user_ids_paginated, get_users_paginated, search_users, get_user_detail,
    get_user_receipts_detailed, block_user, update_user_fields,
    # Receipts
    add_receipt, is_receipt_exists, get_user_receipts, get_user_receipts_count,
    get_user_tickets_count, get_all_receipts_paginated, get_total_receipts_count,
    # Campaigns
    add_campaign, get_pending_campaigns, mark_campaign_completed, 
    get_recent_campaigns,
    # Winners
    get_participants_count, get_participants_with_tickets,
    get_total_tickets_count, save_winners_atomic,
    get_campaign_winners, get_recent_raffles_with_winners, 
    get_all_winners_for_export, get_user_wins, get_raffle_losers,
    mark_winner_notified,
    # Broadcast
    get_broadcast_progress, save_broadcast_progress, delete_broadcast_progress,
    # Stats
    get_stats, get_stats_by_days,
    # Promo
    add_promo_codes, get_promo_code, use_promo_code, get_promo_stats, 
    # Jobs
    add_manual_tickets, get_user_manual_tickets, get_user_total_tickets,
    get_all_tickets_for_final_raffle
)
# Job system not fully ported to bot_methods yet/needs check, assuming they might be missing or handled elsewhere. 
# Checking bot_methods.py again... 
# bot_methods.py doesn't have create_job. It might be needed if upload uses it.
# Adding Job mock/port if needed or import from where it went.
# Wait, create_job was in methods.py. I removed it.
# I should have added create_job to bot_methods.py in step 1.
# I missed create_job. I will add it in next step.
from database.db import init_db, close_db, get_connection
from database.methods import (
    # Bot Management
    get_bot_by_token, get_active_bots, get_bot, get_bot_config, get_all_bots,
    # Bot Admins
    get_bot_admins, add_bot_admin, remove_bot_admin, is_bot_admin,
    update_bot_admins_array,
    # Bot Lifecycle
    get_bot_enabled_modules, update_bot_modules,
    # Users
    add_user, get_user, get_user_by_id, get_user_by_phone,
    get_user_with_stats, update_username, get_total_users_count, get_all_user_ids,
    get_user_ids_paginated, get_users_paginated, search_users, get_user_detail,
    get_user_receipts_detailed, block_user,
    # Receipts
    add_receipt, is_receipt_exists, get_user_receipts, get_user_receipts_count,
    get_user_tickets_count, get_all_receipts_paginated, get_total_receipts_count,
    # Campaigns
    add_campaign, get_pending_campaigns, mark_campaign_completed, get_campaign,
    get_recent_campaigns,
    # Winners
    get_participants_count, get_participants_with_ids, get_participants_with_tickets,
    get_total_tickets_count, save_winners_atomic,
    get_unnotified_winners, mark_winner_notified, get_campaign_winners,
    get_recent_raffles_with_winners, get_all_winners_for_export, get_user_wins,
    get_raffle_losers,
    # Broadcast
    get_broadcast_progress, save_broadcast_progress, delete_broadcast_progress,
    # Health & Stats
    check_db_health, get_stats, get_stats_by_days,
    # Promo
    add_promo_codes, add_promo_codes_bulk, get_promo_code, use_promo_code, get_promo_stats, get_promo_codes_paginated,
    # Jobs
    create_job, update_job, get_active_jobs, get_job, get_recent_jobs,
    # Admin user edit
    update_user_fields,
    # Panel users (admin panel authentication & management)
    get_panel_user, get_panel_user_by_id, update_panel_user_login,
    get_all_panel_users, create_panel_user, update_panel_user, delete_panel_user,
)

