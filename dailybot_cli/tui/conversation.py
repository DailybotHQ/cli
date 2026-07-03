from dataclasses import dataclass, field
from uuid import uuid4

MAX_HISTORY_MESSAGES: int = 20


@dataclass
class ConversationSession:
    """Local terminal conversation state sent with each Dailybot turn."""

    session_id: str = field(default_factory=lambda: str(uuid4()))
    history: list[dict[str, str]] = field(default_factory=list)

    def recent_history(self) -> list[dict[str, str]]:
        """Return the bounded history window sent to the API."""
        return self.history[-MAX_HISTORY_MESSAGES:]

    def append_user(self, content: str) -> None:
        self.history.append({"role": "user", "content": content})

    def append_assistant(self, content: str) -> None:
        self.history.append({"role": "assistant", "content": content})

    def clear(self) -> None:
        self.history.clear()
        self.session_id = str(uuid4())
