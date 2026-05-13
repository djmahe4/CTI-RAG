from ..utils.prompts import get_system_prompt
from ..utils.logging_config import logger

class HistoryManager():
    def __init__(self, history=None, system_prompt=None):
        self.messages = history or []

        system_prompt = system_prompt or get_system_prompt()
        self.add_system(system_prompt)

    def add(self, role, content):
        # Authentication Parameters
        if not role or not isinstance(role, str) or role.strip() == "":
            logger.error(f"Invalid role: {role}")
            return self.messages
        
        if content is None:
            logger.warning(f"Content is None for role {role}, using empty string")
            content = ""
        
        if not isinstance(content, str):
            content = str(content)
            
        self.messages.append({"role": role.strip(), "content": content})
        return self.messages

    def add_user(self, content):
        return self.add("user", content)

    def add_system(self, content):
        if content and content.strip():
            return self.add("system", content)
        else:
            logger.warning("System hint is empty，Skip Add")
            return self.messages

    def add_ai(self, content):
        return self.add("assistant", content)

    def update_ai(self, content):
        if self.messages[-1]["role"] == "assistant":
            self.messages[-1]["content"] = content
            return self.messages
        else:
            self.add_ai(content)
            return self.messages

    def get_history_with_msg(self, msg, role="user", max_rounds=None):
        """Get history with new message, but not append it to history."""
        if max_rounds is None:
            history = self.messages[:]
        else:
            history = self.messages[-(2*max_rounds):]

        # Can not open message
        if msg and isinstance(msg, str) and msg.strip():
            history.append({"role": role, "content": msg})
        else:
            logger.warning(f"Invalid message: {msg}, skipping")
            
        # Can not open message
        validated_history = self._validate_messages(history)
        return validated_history

    def _validate_messages(self, messages):
        """Can not open message，Make sure everything's there.roleandcontentFields"""
        validated = []
        for i, msg in enumerate(messages):
            if not isinstance(msg, dict):
                logger.error(f"Message {i} is not a dict: {msg}")
                continue
                
            if "role" not in msg or not msg["role"]:
                logger.error(f"Message {i} missing role field: {msg}")
                continue
                
            if "content" not in msg:
                logger.warning(f"Message {i} missing content field, adding empty content: {msg}")
                msg["content"] = ""
                
            # Make sure it's a string.
            if not isinstance(msg["content"], str):
                msg["content"] = str(msg["content"])
                
            validated.append(msg)
            
        return validated

    def __str__(self):
        history_str = ""
        for message in self.messages:
            msg = message["content"].replace('\n', ' ')
            history_str += f"\n{message['role']}: {msg}"
        return history_str