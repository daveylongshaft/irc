import logging
from typing import List, Optional
from anthropic import Anthropic

logger = logging.getLogger("csc.claude.api")

class ClaudeAPI:
    """
    Wraps the Anthropic SDK for Claude interaction.
    """
    def __init__(self, api_key: str, model: str = "claude-3-haiku-20240307"):
        # Note: model name adjusted from 'claude-haiku-4-5-20251001' to a verified 3.5 haiku
        # unless a specific haiku 4.5 is confirmed.
        self._client = Anthropic(api_key=api_key)
        self.model = model

    def complete(self, context_lines: List[str], system_prompt: Optional[str] = None) -> str:
        """
        Formats context and sends to Anthropic messages API.
        """
        if not system_prompt:
            system_prompt = (
                "You are Claude, an AI assistant connected to an IRC channel. "
                "Respond concisely. You are seeing recent channel history as context."
            )

        try:
            history_text = "\n".join(context_lines)
            
            response = self._client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": history_text}
                ]
            )
            
            content = response.content[0].text
            return content.strip() if content else ""
            
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            return ""
