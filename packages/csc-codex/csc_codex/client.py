import os

from csc_ai_api import AIClient
from .api import CodexAPI


class CodexClient(AIClient):
    """Codex AI IRC client.

    Implements respond() by calling the OpenAI Codex API with the channel
    backscroll as context. Everything else (connect, identify, standoff,
    ignore, focus, perform scripts) is handled by AIClient.
    """

    def __init__(self, config_path=None, input_file=None, output_file=None):
        super().__init__(config_path=config_path, input_file=input_file, output_file=output_file)
        api_key = self._resolve_api_key()
        model = self._perform.get("ai", "model", "codex-mini-latest")
        self._api = CodexAPI(api_key, model=model)

    def _resolve_api_key(self):
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            return key
        key = self.get_data("codex_api_key")
        if key:
            return key
        raise ValueError(
            "[CodexClient] CRITICAL: No API key found. "
            "Set OPENAI_API_KEY env var or store codex_api_key in the data store."
        )

    def respond(self, context):
        """Call Codex API with backscroll context and return response."""
        if not context:
            return ""
        return self._api.complete(context)
