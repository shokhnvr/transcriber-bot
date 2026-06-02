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
