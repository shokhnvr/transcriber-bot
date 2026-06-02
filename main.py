"""
Telegram-бот для транскрибации аудио через Claude API
Поддерживает: голосовые сообщения, аудио файлы, видео, видеосообщения (кружки)
"""

import os
import logging
import base64
import tempfile
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ─── Настройка логирования ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Переменные окружения ─────────────────────────────────────────────────────
try:
    TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
    ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
except KeyError as e:
    logger.error(f"Ошибка: отсутствует переменная окружения {e}")
    raise

# ─── Языки ────────────────────────────────────────────────────────────────────
LANGUAGES = {
    "auto": "🌐 Авто",
    "ru":   "🇷🇺 Русский",
    "uz":   "🇺🇿 Ўзбекча",
    "en":   "🇬🇧 English",
    "fr":   "🇫🇷 Français",
    "de":   "🇩🇪 Deutsch",
    "es":   "🇪🇸 Español",
    "zh":   "🇨🇳 中文",
    "ar":   "🇸🇦 Arabic",
    "ko":   "🇰🇷 한국어",
}

# Хранилище выбранного языка по user_id (в памяти; для prod используйте Redis/DB)
user_language: dict[int, str] = {}


# ─── Claude API ───────────────────────────────────────────────────────────────
async def transcribe_with_claude(audio_bytes: bytes, mime_type: str, language: str) -> str:
    lang_name = LANGUAGES.get(language, language)
    if language == "auto":
        lang_instruction = "Detect the language automatically."
    else:
        lang_instruction = f"The audio is in {lang_name}. Transcribe accordingly."

    audio_b64 = base64.b64encode(audio_bytes).decode()

    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": audio_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Transcribe the audio content exactly as spoken. "
                            f"{lang_instruction} "
                            f"Return only the transcription text, no commentary or labels."
                        ),
                    },
                ],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            json=payload,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    for block in data.get("content", []):
        if block.get("type") == "text":
            return block["text"].strip()

    return "(пустой результат)"


# ─── Скачивание файла из Telegram ─────────────────────────────────────────────
async def download_telegram_file(file_id: str, context: ContextTypes.DEFAULT_TYPE) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await tg_file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read()


# ─── Определение MIME типа ────────────────────────────────────────────────────
def get_mime_type(file_name: str | None, default: str = "audio/ogg") -> str:
    if not file_name:
        return default
    ext = file_name.rsplit(".", 1)[-1].lower()
    mapping = {
        "ogg":  "audio/ogg",
        "oga":  "audio/ogg",
        "mp3":  "audio/mpeg",
        "wav":  "audio/wav",
        "flac": "audio/flac",
        "m4a":  "audio/mp4",
        "aac":  "audio/aac",
        "mp4":  "video/mp4",
        "webm": "video/webm",
        "mov":  "video/quicktime",
    }
    return mapping.get(ext, default)


# ─── Клавиатура выбора языка ──────────────────────────────────────────────────
def language_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    items = list(LANGUAGES.items())
    for i in range(0, len(items), 2):
        row = [
            InlineKeyboardButton(items[i][1], callback_data=f"lang:{items[i][0]}"),
        ]
        if i + 1 < len(items):
            row.append(
                InlineKeyboardButton(items[i + 1][1], callback_data=f"lang:{items[i + 1][0]}")
            )
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


# ─── Хэндлеры ─────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    logger.info(f"Команда /start от {update.effective_user.id}")
    await update.message.reply_text(
        "🎙 *Бот транскрибации*\n\n"
        "Отправьте голосовое сообщение, аудио файл, видео или кружок — "
        "и я верну текст.\n\n"
        "Команды:\n"
        "/lang — выбрать язык\n"
        "/start — это сообщение",
        parse_mode="Markdown",
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /lang"""
    logger.info(f"Команда /lang от {update.effective_user.id}")
    uid = update.effective_user.id
    current = LANGUAGES.get(user_language.get(uid, "auto"), "🌐 Авто")
    await update.message.reply_text(
        f"Текущий язык: *{current}*\nВыберите язык транскрибации:",
        reply_markup=language_keyboard(),
        parse_mode="Markdown",
    )


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик выбора языка через кнопки"""
    query = update.callback_query
    await query.answer()
    lang_code = query.data.split(":", 1)[1]
    uid = query.from_user.id
    user_language[uid] = lang_code
    logger.info(f"Язык установлен {lang_code} для {uid}")
    await query.edit_message_text(
        f"✅ Язык установлен: *{LANGUAGES[lang_code]}*",
        parse_mode="Markdown",
    )


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Универсальный обработчик для всех типов аудио/видео."""
    msg = update.message
    uid = update.effective_user.id
    language = user_language.get(uid, "auto")

    logger.info(f"Получено аудио/видео от {uid}, язык: {language}")

    # Определяем источник
    if msg.voice:
        file_id   = msg.voice.file_id
        mime_type = "audio/ogg"
        label     = "голосовое сообщение"
    elif msg.audio:
        file_id   = msg.audio.file_id
        mime_type = get_mime_type(msg.audio.file_name, "audio/mpeg")
        label     = msg.audio.file_name or "аудио файл"
    elif msg.video:
        file_id   = msg.video.file_id
        mime_type = get_mime_type(msg.video.file_name, "video/mp4")
        label     = msg.video.file_name or "видео"
    elif msg.video_note:
        file_id   = msg.video_note.file_id
        mime_type = "video/mp4"
        label     = "видеосообщение"
    elif msg.document:
        file_id   = msg.document.file_id
        mime_type = get_mime_type(msg.document.file_name, msg.document.mime_type or "audio/ogg")
        label     = msg.document.file_name or "файл"
    else:
        await msg.reply_text("⚠️ Не удалось распознать тип файла.")
        return

    status_msg = await msg.reply_text(f"⏳ Транскрибирую *{label}*...", parse_mode="Markdown")

    try:
        audio_bytes = await download_telegram_file(file_id, context)
        text = await transcribe_with_claude(audio_bytes, mime_type, language)

        # Telegram ограничивает сообщение 4096 символами
        if len(text) <= 4000:
            await status_msg.edit_text(f"📝 *Транскрипция:*\n\n{text}", parse_mode="Markdown")
        else:
            await status_msg.edit_text("📝 *Транскрипция:*", parse_mode="Markdown")
            # Разбиваем на чанки
            for i in range(0, len(text), 4000):
                await msg.reply_text(text[i:i + 4000])

    except httpx.HTTPStatusError as e:
        logger.error("Claude API error: %s", e.response.text)
        await status_msg.edit_text(f"❌ Ошибка Claude API: {e.response.status_code}")
    except Exception as e:
        logger.exception("Unexpected error")
        await status_msg.edit_text(f"❌ Ошибка: {e}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    logger.info(f"Текстовое сообщение от {update.effective_user.id}: {update.message.text}")
    await update.message.reply_text(
        "ℹ️ Я обрабатываю только аудио и видео файлы.\n\n"
        "Отправьте:\n"
        "• Голосовое сообщение\n"
        "• Аудио файл\n"
        "• Видео\n"
        "• Видеосообщение (кружок)\n\n"
        "Или используйте команды:\n"
        "/lang — выбрать язык\n"
        "/start — справка"
    )


# ─── Запуск ───────────────────────────────────────────────────────────────────
def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Регистрируем обработчики в правильном порядке!
    # 1. Команды (они имеют приоритет)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("lang", language_command))
    
    # 2. Callback query для кнопок
    app.add_handler(CallbackQueryHandler(language_callback, pattern=r"^lang:"))

    # 3. Аудио/видео обработчик
    audio_filter = (
        filters.VOICE
        | filters.AUDIO
        | filters.VIDEO
        | filters.VIDEO_NOTE
        | filters.Document.AUDIO
        | filters.Document.VIDEO
    )
    app.add_handler(MessageHandler(audio_filter, handle_audio))
    
    # 4. Обработчик текстовых сообщений (в конце!)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен. Polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
