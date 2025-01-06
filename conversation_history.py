"""
Conversation history management module.
Handles persistent storage and retrieval of user conversation histories.
Uses JSON file storage for simplicity and persistence between bot restarts.
"""

import os
import json

CONVERSATION_HISTORY_FILE = "conversation_history.json"

def load_conversation_history():
    """
    Load the conversation history from the JSON storage file.
    
    Returns:
        dict: Mapping of user IDs to their conversation histories
    """
    if os.path.exists(CONVERSATION_HISTORY_FILE):
        with open(CONVERSATION_HISTORY_FILE, "r") as file:
            return json.load(file)
    return {}

def save_conversation_history(conversation_history):
    """
    Save the conversation history to persistent storage.
    
    Args:
        conversation_history (dict): Mapping of user IDs to conversation histories
    """
    with open(CONVERSATION_HISTORY_FILE, "w") as file:
        json.dump(conversation_history, file)

def update_conversation_history(user_id, message):
    """
    Add a new message to a user's conversation history.
    Maintains a limited history size per user (default: 10 messages).
    
    Args:
        user_id (str): Discord user ID
        message (str): New message to add to history
    """
    conversation_history = load_conversation_history()
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    conversation_history[user_id].append(message)
    if len(conversation_history[user_id]) > 10:  # Keep only the last 10 messages per user
        conversation_history[user_id] = conversation_history[user_id][-10:]
    save_conversation_history(conversation_history)

def get_user_context(user_id):
    """
    Retrieve recent conversation context for a user.
    Returns the last 5 messages from the user's history.
    
    Args:
        user_id (str): Discord user ID
        
    Returns:
        str: Newline-separated string of recent messages
    """
    conversation_history = load_conversation_history()
    if user_id in conversation_history:
        return "\n".join(conversation_history[user_id][-5:])  # Get the last 5 messages for the user
    return ""
