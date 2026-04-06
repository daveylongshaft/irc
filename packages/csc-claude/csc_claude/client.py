import os

from csc_ai_api import AIClient
from .api import ClaudeAPI


class ClaudeClient(AIClient):
    """Claude AI IRC client."""

    def __init__(self, config_path=None, input_file=None, output_file=None):
        super().__init__(config_path=config_path, input_file=input_file, output_file=output_file)
        api_key = self._resolve_api_key()
        model = self._perform.get("ai", "model", "claude-haiku-4-5-20251001")
        self._api = ClaudeAPI(api_key, model=model)

    def _resolve_api_key(self):
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            return key
        key = self.get_data("claude_api_key")
        if key:
            return key
        raise ValueError(
            "[ClaudeClient] CRITICAL: No API key found. "
            "Set ANTHROPIC_API_KEY env var or store claude_api_key in the data store."
        )

    def respond(self, context):
        if not context:
            return ""
        return self._api.complete(context)
