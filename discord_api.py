import requests
import logging
import time
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_chat_session():
    """
    Creates a new chat session using the GPT Trainer API.

    Returns:
        str: The UUID of the created chat session.

    Raises:
        requests.exceptions.RequestException: If there's an error while making the API request.
    """
    url = f'https://app.gpt-trainer.com/api/v1/chatbot/{os.environ["CHATBOT_UUID"]}/session/create'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.environ["GPT_TRAINER_TOKEN"]}'
    }
    try:
        response = requests.post(url, headers=headers, timeout=30)
        response.raise_for_status()
        logging.info(f"Chat session created. Response: {response.json()}")
        return response.json()['uuid']
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to create chat session. Error: {str(e)}")
        raise

def gpt_response(session_uuid, user_message):
    """
    Sends a user message to the GPT Trainer API and retrieves the generated response.

    Args:
        session_uuid (str): The UUID of the chat session.
        user_message (str): The user's input message.

    Returns:
        str: The generated response from the GPT Trainer API.

    Raises:
        requests.exceptions.RequestException: If there's an error while making the API request.
    """
    url = f'https://app.gpt-trainer.com/api/v1/session/{session_uuid}/message/stream'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.environ["GPT_TRAINER_TOKEN"]}'
    }
    data = {
        'query': user_message
    }
    try:
        response = requests.post(url, headers=headers, json=data, stream=True, timeout=60)
        response.raise_for_status()
        logging.info(f"Sending message to GPT Trainer API. Session UUID: {session_uuid}, User message: {user_message}")

        bot_response = ""
        for line in response.iter_lines(decode_unicode=True):
            if line:
                logging.info(f"Received response from GPT Trainer API: {line}")
                bot_response += line.strip() + "\n"

        # Basic rate limiting
        time.sleep(1)  # Add a 1-second delay between requests

        return bot_response.strip()
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get GPT response. Error: {str(e)}")
        raise