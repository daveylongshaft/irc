from csc_ai_api import AIClient


class DmrClient(AIClient):
    """dmrbot IRC client.

    No external AI API -- respond() implements local rule-based logic.
    Stub implementation: logs the call and returns empty string.
    Real dmrbot logic to be implemented in a future workorder.
    """

    def respond(self, context):
        self.log(f"[dmrbot] respond() called with {len(context)} context lines -- STUB, not yet implemented")
        return ""
