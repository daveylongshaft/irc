import sys


class GeminiAPI:
    """Wraps the Google Generative AI SDK for Gemini model completions.

    API key resolution order:
      1. GOOGLE_API_KEY env var
      2. GEMINI_API_KEY env var
      3. Data store key 'gemini_api_key'
      4. ValueError raised -- startup fails loudly, not silently
    """

    def __init__(self, api_key, model="gemini-2.0-flash"):
        if not api_key:
            raise ValueError(
                "[GeminiAPI] CRITICAL: api_key is empty. "
                "Set GOOGLE_API_KEY or GEMINI_API_KEY or store gemini_api_key in data store."
            )
        try:
            import google.generativeai as genai
        except ImportError as e:
            raise ImportError(
                "[GeminiAPI] CRITICAL: google-generativeai package not installed. "
                "Run: pip install google-generativeai>=0.5.0"
            ) from e

        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)

    def complete(self, context_lines, system_prompt=None):
        prompt = "\n".join(context_lines)
        try:
            response = self._model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[GeminiAPI] ERROR: API call failed: {e}", file=sys.stderr)
            return ""
