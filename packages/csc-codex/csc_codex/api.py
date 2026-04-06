import os


class CodexAPI:
    """Wraps the OpenAI client for Codex model completions.

    API key resolution order:
      1. OPENAI_API_KEY env var
      2. Data store key 'codex_api_key'
      3. ValueError raised -- startup fails loudly, not silently
    """

    def __init__(self, api_key, model="codex-mini-latest"):
        if not api_key:
            raise ValueError(
                "[CodexAPI] CRITICAL: api_key is empty. "
                "Set OPENAI_API_KEY or store codex_api_key in data store."
            )
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "[CodexAPI] CRITICAL: openai package not installed. "
                "Run: pip install openai>=1.0.0"
            ) from e

        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def complete(self, context_lines, system_prompt=None):
        """Send context_lines to the API and return the response text."""
        user_content = "[channel history]\n" + "\n".join(context_lines)
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            # Log but don't crash the IRC loop
            import sys
            print(f"[CodexAPI] ERROR: API call failed: {e}", file=sys.stderr)
            return ""
