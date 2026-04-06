import os
import sys

SYSTEM_PROMPT = (
    "You are Claude, an AI assistant connected to an IRC channel. "
    "Respond concisely. You are seeing recent channel history as context."
)


class ClaudeAPI:
    """Wraps the Anthropic SDK for Claude model completions.

    API key resolution order:
      1. ANTHROPIC_API_KEY env var
      2. Data store key 'claude_api_key'
      3. ValueError raised -- startup fails loudly, not silently
    """

    def __init__(self, api_key, model="claude-haiku-4-5-20251001"):
        if not api_key:
            raise ValueError(
                "[ClaudeAPI] CRITICAL: api_key is empty. "
                "Set ANTHROPIC_API_KEY or store claude_api_key in data store."
            )
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "[ClaudeAPI] CRITICAL: anthropic package not installed. "
                "Run: pip install anthropic>=0.20.0"
            ) from e

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(self, context_lines, system_prompt=None):
        user_content = "\n".join(context_lines)
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=system_prompt or SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            print(f"[ClaudeAPI] ERROR: API call failed: {e}", file=sys.stderr)
            return ""
