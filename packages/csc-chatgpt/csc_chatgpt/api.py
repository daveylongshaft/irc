import logging
from typing import List, Optional
from openai import OpenAI

logger = logging.getLogger("csc.chatgpt.api")

class ChatGPTAPI:
    """
    Wraps the OpenAI client for ChatGPT interaction.
    """
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def complete(self, context_lines: List[str], system_prompt: Optional[str] = None) -> str:
        """
        Formats context and sends to OpenAI chat completions.
        """
        if not system_prompt:
            system_prompt = (
                "You are ChatGPT, an AI assistant connected to an IRC channel. "
                "Respond concisely and helpfully. You are seeing recent channel history as context."
            )

        try:
            history_text = "\n".join(context_lines)
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": history_text}
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=200
            )
            
            content = response.choices[0].message.content
            return content.strip() if content else ""
            
        except Exception as e:
            logger.error(f"ChatGPT API error: {e}")
            return ""
