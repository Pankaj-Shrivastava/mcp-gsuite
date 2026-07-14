import os
import sys
import logging
from typing import Optional
from dotenv import load_dotenv

from mcp.server.fastmcp import FastMCP

from src.tools.docs import create_document as _create_document
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
port = int(os.getenv("MCP_PORT", "8000"))

# Instantiate the MCP server
app = FastMCP("mcp-gsuite", host=host, port=port, dependencies=["google-api-python-client", "google-auth-httplib2", "google-auth-oauthlib"])

@app.tool()
def create_document(title: str, content: str) -> dict:
    """
    Creates a new Google Doc with the given title and populates it with content.
    
    Args:
        title: Title of the document
        content: Initial content
    """
    try:
        return _create_document(title, content)
    except MCPGSuiteError as e:
        return {"error": str(e)}

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
        # Render sets RENDER_EXTERNAL_URL automatically. 
        # If not on render, it will use None and fallback to relative paths.
        external_url = os.getenv("RENDER_EXTERNAL_URL")
        app.run(transport="sse", mount_path=external_url)
    else:
        logger.error(f"Unknown transport: {transport}")
        sys.exit(1)

if __name__ == "__main__":
    main()
