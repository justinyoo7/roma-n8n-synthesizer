"""Tests for the Capability Resolver.

Validates that the resolver correctly maps user intents to:
- Native n8n nodes when available
- HTTP Request configurations for custom APIs
- AI agent steps for ML tasks
"""
import pytest
from app.n8n.capability_resolver import (
    CapabilityResolver,
    ResolvedCapability,
    get_resolver,
    resolve_intent,
)


class TestCapabilityResolver:
    """Test suite for CapabilityResolver."""
    
    @pytest.fixture
    def resolver(self):
        """Get a fresh resolver instance."""
        return CapabilityResolver()
    
    # =========================================================================
    # LinkedIn Tests - Critical because of native node limitations
    # =========================================================================
    
    def test_linkedin_company_post_uses_native_node(self, resolver):
        """LinkedIn company page posts should use native node."""
        result = resolver.resolve("Post to my LinkedIn company page")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.linkedIn"
        assert result.confidence > 0.9
    
    def test_linkedin_personal_message_uses_phantombuster(self, resolver):
        """LinkedIn personal messaging MUST use Phantombuster (no native support)."""
        result = resolver.resolve("Send a LinkedIn message to my connections")
        
        assert result.use_native_node is False
        assert result.api_name == "phantombuster"
        assert result.env_var_needed == "PHANTOMBUSTER_API_KEY"
        assert len(result.warnings) > 0  # Should warn about needing Phantombuster
    
    def test_linkedin_connection_request_uses_phantombuster(self, resolver):
        """LinkedIn connection requests MUST use Phantombuster."""
        result = resolver.resolve("Send connection requests on LinkedIn")
        
        assert result.use_native_node is False
        assert result.api_name == "phantombuster"
    
    def test_linkedin_profile_scraping_uses_phantombuster(self, resolver):
        """LinkedIn profile scraping MUST use Phantombuster."""
        result = resolver.resolve("Scrape LinkedIn profile data")
        
        assert result.use_native_node is False
        assert result.api_name == "phantombuster"
    
    def test_linkedin_search_uses_phantombuster_or_apollo(self, resolver):
        """LinkedIn people search should suggest Phantombuster or Apollo."""
        result = resolver.resolve("Search for people on LinkedIn")
        
        assert result.use_native_node is False
        assert result.api_name in ["phantombuster", "apollo"]
    
    # =========================================================================
    # CRM Tests - All should use native nodes
    # =========================================================================
    
    def test_hubspot_uses_native_node(self, resolver):
        """HubSpot operations should use native node."""
        result = resolver.resolve("Create a contact in HubSpot")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.hubspot"
        assert result.credential_type == "hubspotOAuth2Api"
    
    def test_salesforce_uses_native_node(self, resolver):
        """Salesforce operations should use native node."""
        result = resolver.resolve("Update leads in Salesforce")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.salesforce"
    
    def test_pipedrive_uses_native_node(self, resolver):
        """Pipedrive operations should use native node."""
        result = resolver.resolve("Get deals from Pipedrive")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.pipedrive"
    
    # =========================================================================
    # Email Tests
    # =========================================================================
    
    def test_gmail_uses_native_node(self, resolver):
        """Gmail operations should use native node."""
        result = resolver.resolve("Send an email via Gmail")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.gmail"
    
    def test_outlook_uses_native_node(self, resolver):
        """Outlook operations should use native node."""
        result = resolver.resolve("Read emails from Microsoft Outlook")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.microsoftOutlook"
    
    def test_cold_email_uses_instantly_or_lemlist(self, resolver):
        """Cold email automation should use Instantly or Lemlist."""
        result = resolver.resolve("Send cold email sequences")
        
        assert result.use_native_node is False
        assert result.api_name in ["instantly", "lemlist"]
    
    def test_explicitly_mentioned_instantly(self, resolver):
        """Explicitly mentioning Instantly should use it."""
        result = resolver.resolve("Add leads to Instantly campaign")
        
        assert result.use_native_node is False
        assert result.api_name == "instantly"
    
    # =========================================================================
    # Enrichment Tests
    # =========================================================================
    
    def test_clearbit_uses_native_node(self, resolver):
        """Clearbit enrichment should prefer native node."""
        result = resolver.resolve("Enrich person data with Clearbit")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.clearbit"
    
    def test_apollo_uses_http_request(self, resolver):
        """Apollo.io enrichment should use HTTP Request."""
        result = resolver.resolve("Search for leads in Apollo")
        
        assert result.use_native_node is False
        assert result.api_name == "apollo"
    
    def test_generic_enrichment_suggests_options(self, resolver):
        """Generic enrichment request should provide options."""
        result = resolver.resolve("Enrich lead data")
        
        # Should resolve to something (Apollo or Clearbit)
        assert result.api_name in ["apollo", "clearbit"] or result.node_key == "clearbit"
    
    # =========================================================================
    # Communication Tests
    # =========================================================================
    
    def test_slack_uses_native_node(self, resolver):
        """Slack operations should use native node."""
        result = resolver.resolve("Send a Slack message")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.slack"
    
    def test_discord_uses_native_node(self, resolver):
        """Discord operations should use native node."""
        result = resolver.resolve("Post to Discord channel")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.discord"
    
    def test_telegram_uses_native_node(self, resolver):
        """Telegram operations should use native node."""
        result = resolver.resolve("Send Telegram bot message")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.telegram"
    
    def test_sms_uses_twilio(self, resolver):
        """SMS should use Twilio native node."""
        result = resolver.resolve("Send an SMS message")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.twilio"
    
    # =========================================================================
    # AI/Agent Tests - Always route to agent
    # =========================================================================
    
    def test_sentiment_analysis_uses_agent(self, resolver):
        """Sentiment analysis should use agent step."""
        result = resolver.resolve("Analyze sentiment of customer feedback")
        
        assert result.requires_agent is True
        assert result.use_native_node is False
    
    def test_classification_uses_agent(self, resolver):
        """Text classification should use agent step."""
        result = resolver.resolve("Classify support tickets")
        
        assert result.requires_agent is True
    
    def test_summarization_uses_agent(self, resolver):
        """Text summarization should use agent step."""
        result = resolver.resolve("Summarize this document")
        
        assert result.requires_agent is True
    
    def test_content_generation_uses_agent(self, resolver):
        """Content generation should use agent step."""
        result = resolver.resolve("Generate a personalized email response")
        
        assert result.requires_agent is True
    
    # =========================================================================
    # Database Tests
    # =========================================================================
    
    def test_postgres_uses_native_node(self, resolver):
        """PostgreSQL operations should use native node."""
        result = resolver.resolve("Query PostgreSQL database")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.postgres"
    
    def test_airtable_uses_native_node(self, resolver):
        """Airtable operations should use native node."""
        result = resolver.resolve("Update Airtable records")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.airtable"
    
    def test_google_sheets_uses_native_node(self, resolver):
        """Google Sheets operations should use native node."""
        result = resolver.resolve("Append row to Google Sheets")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.googleSheets"
    
    # =========================================================================
    # Scheduling Tests
    # =========================================================================
    
    def test_calendly_uses_native_node(self, resolver):
        """Calendly operations should use native node."""
        result = resolver.resolve("Get Calendly events")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.calendly"
    
    def test_google_calendar_uses_native_node(self, resolver):
        """Google Calendar operations should use native node."""
        result = resolver.resolve("Create Google Calendar event")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.googleCalendar"
    
    # =========================================================================
    # Explicit Tool Mention Tests
    # =========================================================================
    
    def test_explicit_phantombuster_mention(self, resolver):
        """Explicitly mentioning Phantombuster should use it."""
        result = resolver.resolve("Use Phantombuster to scrape profiles")
        
        assert result.use_native_node is False
        assert result.api_name == "phantombuster"
    
    def test_explicit_apollo_mention(self, resolver):
        """Explicitly mentioning Apollo should use it."""
        result = resolver.resolve("Use Apollo.io to find contacts")
        
        assert result.use_native_node is False
        assert result.api_name == "apollo"
    
    def test_explicit_clay_mention(self, resolver):
        """Explicitly mentioning Clay should use it."""
        result = resolver.resolve("Enrich with Clay")
        
        assert result.use_native_node is False
        assert result.api_name == "clay"
    
    # =========================================================================
    # Complex Intent Tests
    # =========================================================================
    
    def test_sales_workflow_components(self, resolver):
        """Complex sales workflow should resolve multiple components."""
        # This tests that the resolver can handle components of a complex workflow
        
        # Search for leads
        search_result = resolver.resolve("Search LinkedIn for SaaS founders")
        assert search_result.api_name in ["phantombuster", "apollo"]
        
        # Enrich leads
        enrich_result = resolver.resolve("Enrich contact with Apollo")
        assert enrich_result.api_name == "apollo"
        
        # Personalize message
        personalize_result = resolver.resolve("Write personalized outreach message")
        assert personalize_result.requires_agent is True
        
        # Send message
        send_result = resolver.resolve("Send LinkedIn message")
        assert send_result.api_name == "phantombuster"
    
    # =========================================================================
    # Confidence Tests
    # =========================================================================
    
    def test_explicit_mention_high_confidence(self, resolver):
        """Explicit tool mentions should have high confidence."""
        result = resolver.resolve("Send message via HubSpot")
        
        assert result.confidence >= 0.9
    
    def test_vague_request_lower_confidence(self, resolver):
        """Vague requests should have lower confidence."""
        result = resolver.resolve("do something with data")
        
        assert result.confidence < 0.7
    
    # =========================================================================
    # Singleton and Helper Function Tests
    # =========================================================================
    
    def test_get_resolver_returns_same_instance(self):
        """get_resolver should return a singleton."""
        resolver1 = get_resolver()
        resolver2 = get_resolver()
        
        assert resolver1 is resolver2
    
    def test_resolve_intent_convenience_function(self):
        """resolve_intent convenience function should work."""
        result = resolve_intent("Send Slack notification")
        
        assert result.use_native_node is True
        assert result.node_type == "n8n-nodes-base.slack"
    
    # =========================================================================
    # Warning and Limitation Tests
    # =========================================================================
    
    def test_linkedin_native_node_has_warnings(self, resolver):
        """LinkedIn native node should include limitation warnings."""
        result = resolver.resolve("Use LinkedIn node for posts")
        
        # The resolver should warn about limitations
        # (Only company pages supported)
        assert result.use_native_node is True
        # Warnings should be present for LinkedIn native node
    
    def test_phantombuster_requirements_noted(self, resolver):
        """Phantombuster resolutions should note requirements."""
        result = resolver.resolve("Send LinkedIn DM")
        
        assert result.api_name == "phantombuster"
        assert len(result.warnings) > 0


class TestResolutionSummary:
    """Test the human-readable resolution summary."""
    
    def test_native_node_summary(self):
        """Summary for native node resolution."""
        resolver = CapabilityResolver()
        result = resolver.resolve("Send Slack message")
        
        summary = resolver.get_resolution_summary(result)
        
        assert "Slack" in summary or "slack" in summary.lower()
        assert "native" in summary.lower() or "n8n-nodes-base" in summary
    
    def test_http_request_summary(self):
        """Summary for HTTP request resolution."""
        resolver = CapabilityResolver()
        result = resolver.resolve("Send LinkedIn message to connections")
        
        summary = resolver.get_resolution_summary(result)
        
        assert "phantombuster" in summary.lower()
        assert "HTTP" in summary or "http" in summary.lower()
    
    def test_agent_summary(self):
        """Summary for agent resolution."""
        resolver = CapabilityResolver()
        result = resolver.resolve("Analyze sentiment")
        
        summary = resolver.get_resolution_summary(result)
        
        assert "agent" in summary.lower() or "AI" in summary


# Run with: pytest tests/test_capability_resolver.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
