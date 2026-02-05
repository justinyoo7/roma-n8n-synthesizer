"""Database utilities for Supabase integration."""

from app.db.supabase import get_supabase_client, SupabaseClient

__all__ = ["get_supabase_client", "SupabaseClient"]
