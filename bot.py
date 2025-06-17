import os
from pyrogram import Client, filters
from pyrogram.types import Message
import zipfile
import tempfile
import shutil
import requests
import aiofiles
import base64

# No need to load_dotenv for Heroku
API_ID = int(os.getenv("API_ID","12380656"))
API_HASH = os.getenv("API_HASH","d927c13beaaf5110f25c505b7c071273")
BOT_TOKEN = os.getenv("BOT_TOKEN")

app = Client("github_zip_uploader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_data = {}

def reset_user(chat_id):
    if chat_id in user_data:
        del user_data[chat_id]

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply("👋 Send me a .zip file to upload to your GitHub repository.")
    reset_user(message.chat.id)

@app.on_message(filters.document & filters.private)
async def handle_zip(client, message: Message):
    if not message.document.file_name.endswith(".zip"):
        await message.reply("❌ Please upload a `.zip` file.")
        return

    chat_id = message.chat.id
    user_data[chat_id] = {
        "zip_message": message,
        "zip_path": None,
        "github_token": None,
        "repo_name": None,
        "target_folder": None
    }

    # Download the zip file
    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, message.document.file_name)
    await message.download(file_name=zip_path)
    user_data[chat_id]["zip_path"] = zip_path

    await message.reply("✅ Zip file received.\n\n🔑 Now send me your **GitHub personal access token**.")

@app.on_message(filters.text & filters.private)
async def handle_text(client, message: Message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        await message.reply("⚠️ Please send a `.zip` file first.")
        return

    data = user_data[chat_id]

    if not data["github_token"]:
        data["github_token"] = message.text.strip()
        await message.reply("📦 Now send your GitHub **repository name** (e.g., `username/repo`).")
    elif not data["repo_name"]:
        data["repo_name"] = message.text.strip()
        await message.reply("🗂️ Finally, send the **folder path in the repo** where files should go (e.g., `folder/subfolder` or `.` for root).")
    elif not data["target_folder"]:
        data["target_folder"] = message.text.strip()
        await message.reply("⏳ Uploading extracted files to GitHub...")
        await upload_to_github(chat_id, message)

async def upload_to_github(chat_id, message: Message):
    data = user_data[chat_id]
    zip_path = data["zip_path"]
    repo = data["repo_name"]
    token = data["github_token"]
    target_folder = data["target_folder"].strip("/")
    extracted_path = tempfile.mkdtemp()

    try:
        # Extract ZIP
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extracted_path)

        # Walk through files and upload to GitHub
        for root, _, files in os.walk(extracted_path):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, extracted_path)
                github_path = f"{target_folder}/{rel_path}".strip("/")

                # Read content
                async with aiofiles.open(file_path, "rb") as f:
                    content = await f.read()

                # Prepare URL and headers
                url = f"https://api.github.com/repos/{repo}/contents/{github_path}"
                headers = {
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json"
                }

                # Check if file exists to get SHA
                sha = None
                get_resp = requests.get(url, headers=headers)
                if get_resp.status_code == 200:
                    sha = get_resp.json().get("sha")

                payload = {
                    "message": f"Upload {github_path}",
                    "content": content.encode("base64") if isinstance(content, str) else content.encode("base64"),
                    "branch": "main"
                }
                if sha:
                    payload["sha"] = sha

                import base64
                payload["content"] = base64.b64encode(content).decode()

                # Upload
                put_resp = requests.put(url, headers=headers, json=payload)
                if put_resp.status_code not in [200, 201]:
                    await message.reply(f"❌ Failed to upload `{github_path}`: {put_resp.json().get('message')}")
                    return

        await message.reply("✅ All files uploaded to GitHub successfully!")
    except Exception as e:
        await message.reply(f"⚠️ Error: {e}")
    finally:
        shutil.rmtree(os.path.dirname(zip_path), ignore_errors=True)
        shutil.rmtree(extracted_path, ignore_errors=True)
        reset_user(chat_id)

app.run()
