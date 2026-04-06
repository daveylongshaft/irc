import sys

SYSTEM_PROMPT = (
    "You are ChatGPT, an AI assistant connected to an IRC channel. "
    "Respond concisely and conversationally."
)


class ChatGPTAPI:
    """Wraps the OpenAI SDK for GPT-4o completions.

    API key resolution order:
      1. OPENAI_API_KEY env var
      2. Data store key 'chatgpt_api_key'
      3. ValueError raised -- startup fails loudly, not silently
    """

    def __init__(self, api_key, model="gpt-4o"):
        if not api_key:
            raise ValueError(
                "[ChatGPTAPI] CRITICAL: api_key is empty. "
                "Set OPENAI_API_KEY or store chatgpt_api_key in data store."
            )
        try:
            import openai
        except ImportError as e:
            raise ImportError(
                "[ChatGPTAPI] CRITICAL: openai package not installed. "
                "Run: pip install openai>=1.0.0"
            ) from e

        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def complete(self, context_lines, system_prompt=None):
        user_content = "[channel history]\n" + "\n".join(context_lines)
        messages = [
            {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ChatGPTAPI] ERROR: API call failed: {e}", file=sys.stderr)
            return ""
