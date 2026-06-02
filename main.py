"""
Telegram-бот для транскрибации аудио через Groq Whisper API
Поддерживает: голосовые сообщения, аудио файлы, видео, видеосообщения (кружки)
ПОЛНОСТЬЮ БЕСПЛАТНО!
"""

import os
import logging
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
    GROQ_API_KEY = os.environ["GROQ_API_KEY"]
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
    "ar":   "🇸🇦 العربية",
    "ko":   "🇰🇷 한국어",
}

# Хранилище выбранного языка по user_id (в памяти; для prod используйте Redis/DB)
user_language: dict[int, str] = {}


# ─── Groq Whisper API ─────────────────────────────────────────────────────────
async def transcribe_with_groq(audio_bytes: bytes, file_name: str, language: str) -> str:
    """Транскрибирует аудио используя Groq Whisper API (БЕСПЛАТНО!)."""
    
    lang_code = language if language != "auto" else None
    
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            # Подготавливаем multipart form data
            files = {
                "file": (file_name or "audio.ogg", audio_bytes, "audio/ogg"),
                "model": (None, "whisper-large-v3-turbo"),
            }
            
            # Если язык не автоматический, добавляем его
            if lang_code and lang_code != "auto":
                files["language"] = (None, lang_code)
            
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                files=files,
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"Groq Whisper API error: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
            raise

    return data.get("text", "(пустой результат)").strip()


# ─── Скачивание файла из Telegram ─────────────────────────────────────────────
async def download_telegram_file(file_id: str, context: ContextTypes.DEFAULT_TYPE) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        await tg_file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            return f.read()


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
        label     = "голосовое сообщение"
        file_name = "voice.ogg"
    elif msg.audio:
        file_id   = msg.audio.file_id
        label     = msg.audio.file_name or "аудио файл"
        file_name = msg.audio.file_name or "audio.ogg"
    elif msg.video:
        file_id   = msg.video.file_id
        label     = msg.video.file_name or "видео"
        file_name = msg.video.file_name or "video.mp4"
    elif msg.video_note:
        file_id   = msg.video_note.file_id
        label     = "видеосообщение"
        file_name = "video.mp4"
    elif msg.document:
        file_id   = msg.document.file_id
        label     = msg.document.file_name or "файл"
        file_name = msg.document.file_name or "file.ogg"
    else:
        await msg.reply_text("⚠️ Не удалось распознать тип файла.")
        return

    status_msg = await msg.reply_text(f"⏳ Транскрибирую *{label}*...", parse_mode="Markdown")

    try:
        audio_bytes = await download_telegram_file(file_id, context)
        logger.info(f"Файл скачан, размер: {len(audio_bytes)} байт")
        
        text = await transcribe_with_groq(audio_bytes, file_name, language)

        # Telegram ограничивает сообщение 4096 символами
        if len(text) <= 4000:
            await status_msg.edit_text(f"📝 *Транскрипция:*\n\n{text}", parse_mode="Markdown")
        else:
            await status_msg.edit_text("📝 *Транскрипция:*", parse_mode="Markdown")
            # Разбиваем на чанки
            for i in range(0, len(text), 4000):
                await msg.reply_text(text[i:i + 4000])

        logger.info(f"Успешно транскрибировано {len(text)} символов")

    except httpx.HTTPStatusError as e:
        logger.error(f"Groq Whisper API error: {e.response.status_code}")
        logger.error(f"Response: {e.response.text}")
        
        # Парсим ошибку от Groq
        try:
            error_data = e.response.json()
            error_msg = error_data.get("error", {}).get("message", "Неизвестная ошибка")
        except:
            error_msg = e.response.text[:200] if e.response.text else "Неизвестная ошибка"
        
        await status_msg.edit_text(
            f"❌ Ошибка: {e.response.status_code}\n\n`{error_msg}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception("Unexpected error")
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")


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

    logger.info("🎙 Бот транскрибации запущен. Polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
