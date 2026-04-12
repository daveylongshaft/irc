import logging
from typing import List, Optional
from openai import OpenAI

logger = logging.getLogger("csc.codex.api")

class CodexAPI:
    """
    Wraps the OpenAI client for Codex interaction.
    """
    def __init__(self, api_key: str, model: str = "gpt-3.5-turbo"):
        # Note: model name adjusted from 'codex-mini-latest' to a standard gpt-3.5-turbo 
        # unless a specific codex model is verified available.
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def complete(self, context_lines: List[str], system_prompt: Optional[str] = None) -> str:
        """
        Formats context and sends to OpenAI chat completions.
        """
        try:
            history_text = "\n".join(context_lines)
            user_msg = f"[channel history]\n{history_text}"
            
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_msg})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=100
            )
            
            content = response.choices[0].message.content
            return content.strip() if content else ""
            
        except Exception as e:
            logger.error(f"Codex API error: {e}")
            return ""
