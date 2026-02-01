"""Application configuration using Pydantic Settings."""
from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # App settings
    app_name: str = "ROMA Workflow Synthesizer"
    debug: bool = False
    
    # LLM Configuration
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    
    # Default models
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    
    # n8n Configuration
    n8n_base_url: str = "https://app.n8n.cloud/api/v1"
    n8n_api_key: str = ""
    
    # Supabase Configuration
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_anon_key: str = ""
    
    # Agent Runner Configuration
    # This URL must be publicly accessible for n8n Cloud to call it
    # Set this to your deployed agent-runner service URL
    agent_runner_url: str = ""
    agent_runner_timeout: int = 30
    agent_runner_max_tokens: int = 4096
    
    # Synthesis Configuration
    max_iterations: int = 5
    min_passing_score: int = 85
    
    # ==========================================================================
    # CUSTOM API CREDENTIALS
    # These are used when workflows need HTTP Request nodes for non-native APIs
    # ==========================================================================
    
    # Phantombuster - LinkedIn automation, browser automation
    # Get your API key at: https://phantombuster.com/account
    phantombuster_api_key: Optional[str] = None
    
    # Apollo.io - Lead enrichment, people search
    # Get your API key at: https://app.apollo.io/#/settings/integrations/api
    apollo_api_key: Optional[str] = None
    
    # Clearbit - Person/company enrichment (optional, has native n8n node)
    # Get your API key at: https://dashboard.clearbit.com/api
    clearbit_api_key: Optional[str] = None
    
    # Clay - AI-powered data enrichment
    # Get your API key from Clay dashboard
    clay_api_key: Optional[str] = None
    
    # Instantly - Cold email platform
    # Get your API key at: https://app.instantly.ai/app/settings/integrations
    instantly_api_key: Optional[str] = None
    
    # Lemlist - Email outreach automation
    # Get your API key at: https://app.lemlist.com/settings/integrations
    lemlist_api_key: Optional[str] = None
    
    # ZoomInfo - Enterprise lead data (optional)
    zoominfo_api_key: Optional[str] = None
    
    # Perplexity - AI-powered research and web search
    # Get your API key at: https://www.perplexity.ai/settings/api
    perplexity_api_key: Optional[str] = None
    
    # ==========================================================================
    # N8N CREDENTIAL REFERENCES
    # These are the names of credentials configured in n8n Cloud
    # Used when generating workflows that need native integrations
    # ==========================================================================
    
    # CRM credentials (configured in n8n)
    n8n_hubspot_credential: str = "hubspot_oauth"
    n8n_salesforce_credential: str = "salesforce_oauth"
    n8n_pipedrive_credential: str = "pipedrive_api"
    
    # Email credentials (configured in n8n)
    n8n_gmail_credential: str = "gmail_oauth"
    n8n_outlook_credential: str = "outlook_oauth"
    n8n_sendgrid_credential: str = "sendgrid_api"
    
    # Communication credentials (configured in n8n)
    n8n_slack_credential: str = "slack_oauth"
    n8n_telegram_credential: str = "telegram_api"
    n8n_twilio_credential: str = "twilio_api"
    
    # Database credentials (configured in n8n)
    n8n_postgres_credential: str = "postgres_connection"
    n8n_airtable_credential: str = "airtable_api"
    n8n_google_sheets_credential: str = "google_sheets_oauth"
    
    # Enrichment credentials (configured in n8n)
    n8n_clearbit_credential: str = "clearbit_api"
    n8n_hunter_credential: str = "hunter_api"
    
    def get_api_key(self, api_name: str) -> Optional[str]:
        """Get API key for a specific integration."""
        key_map = {
            "phantombuster": self.phantombuster_api_key,
            "apollo": self.apollo_api_key,
            "clearbit": self.clearbit_api_key,
            "clay": self.clay_api_key,
            "instantly": self.instantly_api_key,
            "lemlist": self.lemlist_api_key,
            "zoominfo": self.zoominfo_api_key,
            "perplexity": self.perplexity_api_key,
        }
        return key_map.get(api_name.lower())
    
    def get_n8n_credential(self, integration: str) -> str:
        """Get n8n credential name for a native integration."""
        credential_map = {
            "hubspot": self.n8n_hubspot_credential,
            "salesforce": self.n8n_salesforce_credential,
            "pipedrive": self.n8n_pipedrive_credential,
            "gmail": self.n8n_gmail_credential,
            "outlook": self.n8n_outlook_credential,
            "sendgrid": self.n8n_sendgrid_credential,
            "slack": self.n8n_slack_credential,
            "telegram": self.n8n_telegram_credential,
            "twilio": self.n8n_twilio_credential,
            "postgres": self.n8n_postgres_credential,
            "airtable": self.n8n_airtable_credential,
            "google_sheets": self.n8n_google_sheets_credential,
            "clearbit": self.n8n_clearbit_credential,
            "hunter": self.n8n_hunter_credential,
        }
        return credential_map.get(integration.lower(), f"{integration}_credential")
    
    def has_api_key(self, api_name: str) -> bool:
        """Check if an API key is configured."""
        key = self.get_api_key(api_name)
        return bool(key)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
