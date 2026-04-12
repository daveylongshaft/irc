import os
import logging
from typing import List, Optional
from csc_ai_api import AIClient
from .api import ClaudeAPI

logger = logging.getLogger("csc.claude.client")

class ClaudeClient(AIClient):
    """
    Claude AI IRC client.
    """
    def __init__(self, config_path: Optional[str] = None, input_file: Optional[str] = None, output_file: Optional[str] = None):
        super().__init__(config_path=config_path, input_file=input_file, output_file=output_file)
        
        try:
            api_key = self._resolve_api_key()
            self._api = ClaudeAPI(api_key)
        except ValueError as e:
            self.log(f"[ClaudeClient] Configuration error: {e}", level="ERROR")
            self._api = None

    def _resolve_api_key(self) -> str:
        """
        Resolves the API key from environment or data store.
        """
        # 1. Environment variable
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key
        
        # 2. Data store
        key = self.get_data("claude_api_key")
        if key:
            return key
            
        raise ValueError("ANTHROPIC_API_KEY not set and claude_api_key not found in data store.")

    def respond(self, context: List[str]) -> Optional[str]:
        """
        Generates a response using the Claude API.
        """
        if not self._api:
            return None
        return self._api.complete(context)
