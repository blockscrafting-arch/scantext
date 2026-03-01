"""
Приём фото и документов (PDF), постановка в очередь на обработку.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from app.models import Document
from bot.services.user import get_or_create_user, refund_user_limit, spend_user_limit

logger = logging.getLogger(__name__)

router = Router(name="documents")


def _get_file_id_and_name(message: Message) -> tuple[str, str | None, str | None]:
    """Извлекает file_id, file_name, mime_type из сообщения (фото или документ)."""
    if message.photo:
        photo = message.photo[-1]
        return photo.file_id, None, "image/jpeg"
    if message.document:
        doc = message.document
        return doc.file_id, doc.file_name, doc.mime_type
    return "", None, None


@router.message(F.photo | F.document)
async def on_document(message: Message, session) -> None:
    """Принимает фото или PDF, списывает лимит, ставит задачу в Celery."""
    user_tg = message.from_user
    if not user_tg:
        return

    await message.answer("Проверяю файл…")

    try:
        user = await get_or_create_user(
            session,
            tg_id=user_tg.id,
            username=user_tg.username,
            first_name=user_tg.first_name,
            last_name=user_tg.last_name,
        )
        ok, ded_free, ded_paid = await spend_user_limit(session, user, amount=1)
        if not ok:
            await message.answer("Лимит исчерпан. Используйте /buy для покупки.")
            return

        file_id, file_name, mime_type = _get_file_id_and_name(message)
        if not file_id:
            await message.answer("Не удалось получить файл. Отправьте фото или PDF ещё раз.")
            await refund_user_limit(session, user, ded_free, ded_paid)
            return
        file_unique_id = None
        if message.document:
            file_unique_id = message.document.file_unique_id
        elif message.photo:
            file_unique_id = message.photo[-1].file_unique_id

        doc = Document(
            user_id=user.id,
            telegram_file_id=file_id,
            telegram_file_unique_id=file_unique_id,
            file_name=file_name,
            mime_type=mime_type,
            status="pending",
            deducted_free=ded_free,
            deducted_paid=ded_paid,
        )
        session.add(doc)
        await session.flush()
        await session.commit()  # воркер читает БД в другом процессе — без commit документа не видно

        try:
            from celery_app import process_document_task
            result = process_document_task.delay(doc.id, file_id)
            doc.celery_task_id = result.id
            await session.commit()
        except Exception as e:
            logger.exception("Failed to enqueue document %s: %s", doc.id, e)
            await refund_user_limit(session, user, ded_free, ded_paid)
            await message.answer(
                "Сервис обработки временно недоступен. Ваш лимит не списан — попробуйте отправить файл через минуту."
            )
            return

        await message.answer(
            "Файл принят. Распознавание текста (AI) займёт до минуты, для PDF — дольше. "
            "Результат придёт сюда отдельным сообщением. Если расшифровка не пришла за 2–3 минуты — напишите в поддержку."
        )
        try:
            from aiogram.enums import ChatAction
            await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
        except Exception:
            pass
    except Exception as e:
        logger.exception("Error processing document from user %s: %s", user_tg.id, e)
        await message.answer(
            "Произошла ошибка при обработке файла. Попробуйте позже или обратитесь в поддержку."
        )
