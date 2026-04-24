from typing import Dict, Any

class Store:
    def __init__(self):
        self.messages: Dict[str, Any] = {}

    def add_message(self, message: Any):
        self.messages[message.Info.ID] = [message]

    def get_message(self, id: str):
        return self.messages.get(id)

store = Store()
