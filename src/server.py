import os
import sys
import logging
from typing import Optional
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP

from src.tools.docs import append_to_document as _append_to_document
from src.exceptions import MCPGSuiteError

load_dotenv()

# Configure logging
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level_str, logging.INFO), 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

host = os.getenv("MCP_HOST", "0.0.0.0")
# Railway and most PaaS platforms inject a dynamic PORT env var.
# Check MCP_PORT first (explicit), then PORT (PaaS convention), then default.
port = int(os.getenv("MCP_PORT") or os.getenv("PORT") or "8000")

# Instantiate the MCP server
app = FastMCP("mcp-gsuite", host=host, port=port, dependencies=["google-api-python-client", "google-auth-httplib2", "google-auth-oauthlib"])

from starlette.middleware.base import BaseHTTPMiddleware
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        logger.info(f"Incoming request: {request.method} {request.url}")
        response = await call_next(request)
        logger.info(f"Response status: {response.status_code}")
        return response

app._custom_starlette_routes = getattr(app, '_custom_starlette_routes', [])
# We'll inject the middleware into the starlette app by overriding the run method temporarily
# Actually, the easiest way to see logs on Render is just to patch the app instance before calling run.
# But app.run() creates the Starlette app internally.

@app.tool()
def append_to_document(document_id: str, content: str) -> dict:
    """
    Appends new content to the end of an existing Google Doc.
    
    Args:
        document_id: ID of the document
        content: Content to append
    """
    try:
        return _append_to_document(document_id, content)
    except MCPGSuiteError as e:
        return {"error": str(e)}



def main():
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    
    if transport == "stdio":
        logger.info("Starting mcp-gsuite via stdio transport")
        app.run(transport="stdio")
    elif transport == "sse":
        logger.info(f"Starting mcp-gsuite via sse transport on {app.settings.host}:{app.settings.port}")
        import uvicorn
        from starlette.routing import Route, Mount
        
        starlette_app = app.sse_app()
        
        # Cursor MCP client has a bug where it POSTs messages to the base /sse URL
        # instead of the /messages/ URL provided in the endpoint event.
        # We patch the /sse route to accept POST and forward to the messages handler.
        sse_route = None
        message_app = None
        
        for route in starlette_app.routes:
            if isinstance(route, Route) and route.path == "/sse":
                sse_route = route
            elif isinstance(route, Mount) and route.path == "/messages":
                message_app = route.app
                
        if sse_route and message_app:
            original_endpoint = sse_route.endpoint
            
            async def combined_endpoint(scope, receive, send):
                if scope["method"] == "POST":
                    await message_app(scope, receive, send)
                else:
                    await original_endpoint(scope, receive, send)
                    
            sse_route.endpoint = combined_endpoint
            if sse_route.methods:
                sse_route.methods.add("POST")
        
        uvicorn.run(starlette_app, host=app.settings.host, port=app.settings.port)
    else:
        logger.error(f"Unknown transport: {transport}")
        sys.exit(1)

if __name__ == "__main__":
    main()
