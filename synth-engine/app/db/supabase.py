"""Supabase client utility for database operations.

Provides a singleton Supabase client for backend database operations.
Uses service key for backend operations (bypasses RLS).
"""
from typing import Optional

import structlog
from supabase import create_client, Client

from app.config import get_settings

logger = structlog.get_logger()

# Singleton client instance
_supabase_client: Optional[Client] = None


class SupabaseClient:
    """Wrapper for Supabase client with convenience methods."""
    
    def __init__(self, client: Client):
        self._client = client
    
    @property
    def client(self) -> Client:
        """Get the underlying Supabase client."""
        return self._client
    
    async def insert(self, table: str, data: dict) -> dict:
        """Insert a row into a table.
        
        Args:
            table: Table name
            data: Row data to insert
            
        Returns:
            Inserted row data
        """
        try:
            result = self._client.table(table).insert(data).execute()
            return result.data[0] if result.data else {}
        except Exception as e:
            logger.error("supabase_insert_error", table=table, error=str(e))
            raise
    
    async def insert_many(self, table: str, data: list[dict]) -> list[dict]:
        """Insert multiple rows into a table.
        
        Args:
            table: Table name
            data: List of row data to insert
            
        Returns:
            List of inserted row data
        """
        try:
            result = self._client.table(table).insert(data).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error("supabase_insert_many_error", table=table, count=len(data), error=str(e))
            raise
    
    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: Optional[dict] = None,
        limit: Optional[int] = None,
        order_by: Optional[str] = None,
        descending: bool = False,
    ) -> list[dict]:
        """Select rows from a table.
        
        Args:
            table: Table name
            columns: Columns to select (default "*")
            filters: Filter conditions as {column: value}
            limit: Maximum number of rows
            order_by: Column to order by
            descending: Whether to order descending
            
        Returns:
            List of matching rows
        """
        try:
            query = self._client.table(table).select(columns)
            
            if filters:
                for col, val in filters.items():
                    query = query.eq(col, val)
            
            if order_by:
                query = query.order(order_by, desc=descending)
            
            if limit:
                query = query.limit(limit)
            
            result = query.execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error("supabase_select_error", table=table, error=str(e))
            raise
    
    async def update(self, table: str, data: dict, filters: dict) -> list[dict]:
        """Update rows in a table.
        
        Args:
            table: Table name
            data: Data to update
            filters: Filter conditions to identify rows
            
        Returns:
            List of updated rows
        """
        try:
            query = self._client.table(table).update(data)
            for col, val in filters.items():
                query = query.eq(col, val)
            result = query.execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error("supabase_update_error", table=table, error=str(e))
            raise
    
    async def delete(self, table: str, filters: dict) -> list[dict]:
        """Delete rows from a table.
        
        Args:
            table: Table name
            filters: Filter conditions to identify rows
            
        Returns:
            List of deleted rows
        """
        try:
            query = self._client.table(table).delete()
            for col, val in filters.items():
                query = query.eq(col, val)
            result = query.execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error("supabase_delete_error", table=table, error=str(e))
            raise


def get_supabase_client() -> Optional[SupabaseClient]:
    """Get the singleton Supabase client instance.
    
    Returns:
        SupabaseClient instance, or None if not configured
    """
    global _supabase_client
    
    if _supabase_client is None:
        settings = get_settings()
        
        if not settings.supabase_url or not settings.supabase_service_key:
            logger.warning(
                "supabase_not_configured",
                has_url=bool(settings.supabase_url),
                has_key=bool(settings.supabase_service_key),
            )
            return None
        
        try:
            _supabase_client = create_client(
                settings.supabase_url,
                settings.supabase_service_key,
            )
            logger.info("supabase_client_initialized")
        except Exception as e:
            logger.error("supabase_client_init_error", error=str(e))
            return None
    
    return SupabaseClient(_supabase_client)


def reset_supabase_client():
    """Reset the Supabase client (for testing)."""
    global _supabase_client
    _supabase_client = None
