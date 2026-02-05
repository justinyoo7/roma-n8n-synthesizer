"""FastAPI application entry point."""
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api import synthesize, iterate, simplify, agent_run, n8n, test

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="ROMA-style workflow synthesizer for n8n",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for Lovable frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(synthesize.router, prefix="/api", tags=["synthesis"])
app.include_router(iterate.router, prefix="/api", tags=["iteration"])
app.include_router(simplify.router, prefix="/api", tags=["simplification"])
app.include_router(agent_run.router, prefix="/api", tags=["agent"])
app.include_router(n8n.router, prefix="/api", tags=["n8n"])
app.include_router(test.router, prefix="/api", tags=["testing"])


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "llm_provider": settings.llm_provider,
    }


@app.get("/debug/supabase")
async def debug_supabase():
    """Debug endpoint to test Supabase connectivity and query logging."""
    from app.db.supabase import get_supabase_client
    from app.llm.query_logger import log_query
    
    results = {
        "supabase_url_configured": bool(settings.supabase_url),
        "supabase_key_configured": bool(settings.supabase_service_key),
    }
    
    # Test Supabase client
    client = get_supabase_client()
    if client:
        results["supabase_client"] = "connected"
        
        # Try to insert a test query
        try:
            log_result = await log_query(
                node_name="Debug Test",
                query_text="This is a test query from debug endpoint",
                model="debug-test",
                status="success",
                input_tokens=10,
                output_tokens=20,
                latency_ms=100,
                cost_usd=0.001,
            )
            results["test_insert"] = "success" if log_result else "returned_none"
            results["inserted_row"] = log_result
        except Exception as e:
            results["test_insert"] = "failed"
            results["insert_error"] = str(e)
    else:
        results["supabase_client"] = "not_configured"
    
    return results


@app.on_event("startup")
async def startup_event():
    """Application startup handler."""
    logger.info(
        "application_startup",
        app_name=settings.app_name,
        debug=settings.debug,
        llm_provider=settings.llm_provider,
    )


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown handler."""
    logger.info("application_shutdown")
