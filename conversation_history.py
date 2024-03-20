import os
import json

CONVERSATION_HISTORY_FILE = "conversation_history.json"

def load_conversation_history():
    if os.path.exists(CONVERSATION_HISTORY_FILE):
        with open(CONVERSATION_HISTORY_FILE, "r") as file:
            return json.load(file)
    return {}

def save_conversation_history(conversation_history):
    with open(CONVERSATION_HISTORY_FILE, "w") as file:
        json.dump(conversation_history, file)

def update_conversation_history(user_id, message):
    conversation_history = load_conversation_history()
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    conversation_history[user_id].append(message)
    if len(conversation_history[user_id]) > 10:  # Keep only the last 10 messages per user
        conversation_history[user_id] = conversation_history[user_id][-10:]
    save_conversation_history(conversation_history)

def get_user_context(user_id):
    conversation_history = load_conversation_history()
    if user_id in conversation_history:
        return "\n".join(conversation_history[user_id][-5:])  # Get the last 5 messages for the user
    return ""
