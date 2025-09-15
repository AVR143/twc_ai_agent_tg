import os
import aiohttp
import asyncio
import logging
from collections import defaultdict
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes



logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def process_env_string(s):
    if not s:
        return s
    s = s.strip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    return s.replace('\\n', '\n').replace('\\t', '\t')


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AI_TOKEN = os.getenv("AI_API_KEY")
AGENT_ID = os.getenv("AGENT_ID")
MAX_MSG_LEN = 4096
HI_MSG = process_env_string(os.getenv("HI_MSG", "Добро пожаловать!"))
ERR_MSG = process_env_string(os.getenv("ERR_MSG", "Извините, сейчас не могу ответить. Попробуйте позже."))


user_locks = defaultdict(asyncio.Lock)

async def call_ai(message: str, parent_message_id: str = ""):
    try:
        url = f"https://api.timeweb.cloud/api/v1/cloud-ai/agents/{AGENT_ID}/call"
        payload = {
            "message": message,
            "parent_message_id": parent_message_id
        }
        headers = {
            "authorization": f"Bearer {AI_TOKEN}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=300) as response:
                response.raise_for_status()
                data = await response.json()
                return data["id"], data["message"]

    except aiohttp.ClientError as e:
        logger.error(f"Ошибка запроса к AI API: {e}", exc_info=True)
        return None, None
    except asyncio.TimeoutError:
        logger.error(f"Таймаут запроса к AI API", exc_info=True)
        return None, None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при вызове AI: {e}", exc_info=True)
        return None, None


def split_message(text: str, max_len: int = MAX_MSG_LEN):
    parts = []
    while len(text) > max_len:
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        parts.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        parts.append(text)
    return parts


async def safe_reply(update: Update, text: str):
    try:
        for part in split_message(text):
            await update.message.reply_text(part, parse_mode="Markdown")
    except TelegramError as e:
        logger.error(f"Ошибка при отправке сообщения в Telegram: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отправке сообщения: {e}", exc_info=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply(update, HI_MSG)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    asyncio.create_task(process_message(update, context))

async def process_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    async with user_locks[chat_id]:
        user_message = update.message.text
        parent_message_id = context.user_data.get("last_message_id", "")

        msg_id, ai_response = await call_ai(user_message, parent_message_id)

        if ai_response:
            context.user_data["last_message_id"] = msg_id
            await safe_reply(update, ai_response)
        else:
            await safe_reply(update, ERR_MSG)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
  
