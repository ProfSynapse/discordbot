# DiscordBot with GPT Trainer API

This Discord bot integrates with the [GPT Trainer API](https://guide.gpt-trainer.com/api-key) to provide interactive conversations and generate responses based on user prompts with an uploaded knowledge base and capabilities for a multi-agent system. It allows users to chat with a virtual assistant powered by the GPT Trainer API.

## Features

- Interact with the bot using the `/prof` command followed by a prompt (this can easily be changed in the code, by replacing wherever it says "prof" with whatever you want)
- The bot generates a response using the GPT Trainer API based on the provided prompt and your uploaded sources.
- Supports handling long responses by splitting them into multiple messages
- Implements basic rate limiting to avoid excessive API requests

## Prerequisites

* **Python 3.x:** 
    * **Download:** Ensure you have the latest version from the official Python website: [https://www.python.org/downloads/](https://www.python.org/downloads/)
    * **Installation:** Follow the instructions for your operating system.

* **Discord Bot Token:**
    1. **Discord Developer Portal:** Visit [Dev Portal](https://discord.com/developers/applications)
    2. **Create an Application:** Click "New Application" and give your bot a name.
    3. **Bot Creation:** Navigate to the "Bot" tab and click "Add Bot".
    4. **Token:** Under the bot's profile, you'll see a "Token" section. Click "Copy" to obtain your token. **Keep this token secure!**

* **GPT Trainer API Token and Chatbot UUID:** 
    1. **GPT Trainer Website:**  Visit [https://gpt-trainer.com/](https://gpt-trainer.com/) 
    2. **Account Creation:** Create an account.
    3. **Create a Chatbot:** Follow the GPT Trainer platform's instructions to create a new chatbot project.
    4. **API Token and UUID:** Within your chatbot project settings, you should find your API token and the chatbot's unique UUID.  

**Additional Notes**

* **GPT Trainer Documentation:** Refer to the official documentation on the GPT Trainer website for the most up-to-date guidance on setting up your chatbot and obtaining the prerequisites. 
* **Code Examples:** GPT Trainer likely provides code examples or a library to ease the interaction between your Discord bot and their service.

## Getting Started

### 1. Set Up the Discord Bot
1. Go to the Discord Developer Portal: https://discord.com/developers/applications
2. Click on "New Application" and give your bot a name.
3. In the left sidebar, click on "Bot" and then click on "Add Bot".
4. Customize your bot's name and profile picture if desired.
5. Under the "Token" section, click on "Copy" to copy your bot token. Keep this token secure and do not share it with anyone.
6. In the left sidebar, click on "OAuth2" and then click on "URL Generator".
7. Under "Scopes", select "bot".
8. Under "Bot Permissions", select the permissions your bot requires (e.g., "Send Messages", "Read Message History").
9. Copy the generated OAuth2 URL and paste it into your web browser.
10. Select the Discord server you want to add the bot to and click on "Authorize".

### 2. Clone the Repository

1. Install Git on your computer if you haven't already. You can download it from the official website: [https://git-scm.com/downloads](https://git-scm.com/downloads)

2. Open a terminal or command prompt and navigate to the directory where you want to store the project.

3. Run the following command to clone the repository:
   ```
   git clone https://github.com/your-username/your-repo.git
   ```
   Replace `your-username` with your GitHub username and `your-repo` with the name of the repository.

### 3. Set Up the Development Environment

1. Install Visual Studio Code (VS Code) on your computer. You can download it from the official website: [https://code.visualstudio.com/download](https://code.visualstudio.com/download)

2. Open VS Code and go to File -> Open Folder. Navigate to the directory where you cloned the repository and select it.

3. Open a terminal within VS Code by going to Terminal -> New Terminal.

4. Run the following command to create a virtual environment:
   ```
   python -m venv venv
   ```

### 4. Activate the virtual environment:
   - For Windows:
     ```
     venv\Scripts\activate
     ```
   - For macOS and Linux:
     ```
     source venv/bin/activate
     ```

6. Install the required dependencies by running the following command:
   ```
   pip install -r requirements.txt
   ```

### 5. Configure the Bot

1. Create a new file named `.env` in the project directory.

2. Open the `.env` file and add the following lines:
   ```
   DISCORD_TOKEN=your-discord-bot-token
   GPT_TRAINER_TOKEN=your-gpt-trainer-api-token
   CHATBOT_UUID=your-gpt-trainer-chatbot-uuid
   ```
   Replace `your-discord-bot-token`, `your-gpt-trainer-api-token`, and `your-gpt-trainer-chatbot-uuid` with your actual tokens and UUID.

   *The UUID can be found in your chatbot's dashboard in the top left under your Chatbots name.*

### 6. Run the Bot

1. In the VS Code terminal, run the following command to start the bot:
   ```
   python main.py
   ```

2. The bot should now be running and connected to your Discord server.

## Hosting the Bot

If you want to host the bot continuously without running it on your local machine, you can use platforms like Replit or Railway.

### Hosting on Replit

1. Sign up for a free account on [Replit](https://replit.com/).(Note you will need to purchase an account to keep it continuosly running.

2. Click on the "+" button to create a new repl.

3. Select "Python" as the language and give your repl a name.

4. In the Replit editor, upload the files from your local project directory (`main.py`, `discord_api.py`).

5. Open the "Secrets" tab (bottom left in the list) and add in all of your keys (Bot token, GPT Trainer API, UUID for your chatbot)

6. Click on the "Run" button to start the bot.

7. Keep the Replit tab open to keep the bot running continuously.

### Hosting on Railway

1. Sign up for a free account on [Railway](https://railway.app/).

2. Create a new project and select "Deploy from GitHub".

3. Connect your GitHub account and select the repository containing your bot code.

4. Configure the environment variables (Discord bot token, GPT Trainer API token, and chatbot UUID) in the Railway dashboard.

5. Click on "Deploy" to deploy your bot.

6. Railway will provide you with a URL where your bot is hosted and running continuously.

## Usage

1. Invite the bot to your Discord server using the OAuth2 URL generated in the Discord Developer Portal.

2. Use the `/prof` command followed by a prompt to interact with the bot. For example:
   ```
   /prof What is the meaning of life?
   ```

3. The bot will generate a response based on the provided prompt and send it back to the Discord channel.


## Roadmap
1. Add ability to find and summarize shared links.

## Contributing

Contributions are welcome! If you find any issues or have suggestions for improvements, please open an issue or submit a pull request.

## License

This project is licensed under the MIT License.
