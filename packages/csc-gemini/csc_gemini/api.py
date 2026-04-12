import logging
from typing import List, Optional
import google.generativeai as genai

logger = logging.getLogger("csc.gemini.api")

class GeminiAPI:
    """
    Wraps the Google Generative AI SDK for Gemini interaction.
    """
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(model)

    def complete(self, context_lines: List[str], system_prompt: Optional[str] = None) -> str:
        """
        Formats context and sends to Gemini generation API.
        """
        try:
            prompt = "\n".join(context_lines)
            if system_prompt:
                prompt = f"{system_prompt}\n\n{prompt}"
                
            response = self._model.generate_content(prompt)
            return response.text.strip() if response and response.text else ""
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return ""
