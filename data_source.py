import requests
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def upload_data_source(url):
    api_url = f'https://app.gpt-trainer.com/api/v1/chatbot/{os.environ["CHATBOT_UUID"]}/data-source/url'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.environ["GPT_TRAINER_TOKEN"]}'
    }
    data = {
        'url': url
    }

    try:
        response = requests.post(api_url, headers=headers, json=data)
        response.raise_for_status()
        logging.info(f"Data source uploaded successfully. URL: {url}")
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to upload data source. Error: {str(e)}")
        raise
