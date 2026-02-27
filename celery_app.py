"""
Celery app: брокер Redis, задачи обработки документов (OCR через LLM Vision, PDF).
"""
from __future__ import annotations

# ruff: noqa: E402 — imports below depend on setup_logging / config
import logging
import os
import time
from datetime import datetime, timezone
from io import BytesIO

import httpx
from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

@setup_logging.connect
def setup_celery_logging(**kwargs):
    try:
        import sys
        from pythonjsonlogger import jsonlogger
        formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        logging.root.addHandler(handler)
        logging.root.setLevel(logging.INFO)
    except ImportError:
        pass

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker, selectinload

from app.models import Document, User
from app.services.settings import get_setting_str_sync
from config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

if settings.SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        integrations=[CeleryIntegration()],
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )
    logger.info("Sentry initialized for Celery worker")

if not (getattr(settings, "OPENROUTER_API_KEY", "") or "").strip():
    logger.warning(
        "OPENROUTER_API_KEY не задан. Добавьте в .env в корне проекта и перезапустите воркер — иначе запросы к ИИ не пойдут."
    )

celery_app = Celery(
    "elenabot",
    broker=settings.get_celery_broker_url(),
    backend=settings.get_celery_result_backend(),
    include=["celery_app"],
)
# На Windows prefork падает с PermissionError (billiard); solo — один процесс, без fork
_is_windows = os.name == "nt"
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    time_zone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    max_tasks_per_child=10,
    worker_pool="solo" if _is_windows else "prefork",
)

# Расписание сброса бесплатных лимитов (по умолчанию 1-е число месяца, 00:00 UTC)
def _get_limit_reset_schedule():
    """Парсит LIMIT_RESET_CRON (формат: минута час день_месяца месяц день_недели)."""
    cron_str = getattr(settings, "LIMIT_RESET_CRON", "0 0 1 * *") or "0 0 1 * *"
    cron_str = cron_str.strip()
    if len(cron_str.split()) != 5:
        return crontab(minute=0, hour=0, day_of_month=1)
    return crontab.from_string(cron_str)

# Зависшие документы: старше N минут в pending/processing — возврат лимита и пометка error
STALE_DOCUMENT_MINUTES = 30

celery_app.conf.beat_schedule = {
    "reset-free-limits": {
        "task": "celery_app.reset_free_limits_task",
        "schedule": _get_limit_reset_schedule(),
    },
    "cleanup-stale-documents": {
        "task": "celery_app.cleanup_stale_documents_task",
        "schedule": crontab(minute="*/15"),  # каждые 15 минут
    },
}

# Синхронная сессия БД для воркера
sync_engine = create_engine(
    settings.get_database_url_sync(), 
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
)
SyncSession = sessionmaker(sync_engine, expire_on_commit=False, autocommit=False, autoflush=False)


# HTTP client session for reuse across tasks
http_client = httpx.Client(timeout=60.0, limits=httpx.Limits(max_keepalive_connections=20, max_connections=100))

# Maximum file size allowed to process (default 20MB to protect memory)
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

def _download_telegram_file(file_id: str) -> bytes:
    """Скачивает файл по file_id через Telegram Bot API."""
    token = settings.BOT_TOKEN
    r = http_client.get(f"https://api.telegram.org/bot{token}/getFile", params={"file_id": file_id})
    r.raise_for_status()
    file_info = r.json()["result"]
    file_size = file_info.get("file_size", 0)
    
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File size ({file_size} bytes) exceeds the allowed limit of {MAX_FILE_SIZE_BYTES} bytes.")
        
    path = file_info["file_path"]
    r2 = http_client.get(f"https://api.telegram.org/file/bot{token}/{path}")
    r2.raise_for_status()
    return r2.content

def _send_telegram_message(chat_id: int, text: str, parse_mode: str | None = "HTML") -> None:
    """Отправляет сообщение пользователю от имени бота."""
    token = settings.BOT_TOKEN
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = http_client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=30.0)
    r.raise_for_status()

def _send_telegram_document(chat_id: int, file_bytes: bytes, filename: str = "result.txt") -> None:
    """Отправляет файл пользователю в чат."""
    token = settings.BOT_TOKEN
    r = http_client.post(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data={"chat_id": chat_id},
        files={"document": (filename, file_bytes, "text/plain")},
        timeout=60.0,
    )
    r.raise_for_status()

def _send_telegram_photo(chat_id: int, photo_file_id: str, caption: str = "") -> None:
    """Отправляет фото по file_id (из Telegram)."""
    token = settings.BOT_TOKEN
    payload = {"chat_id": chat_id, "photo": photo_file_id}
    if caption:
        payload["caption"] = caption[:1024]
    r = http_client.post(f"https://api.telegram.org/bot{token}/sendPhoto", json=payload, timeout=30.0)
    r.raise_for_status()

def _send_telegram_video(chat_id: int, video_file_id: str, caption: str = "") -> None:
    """Отправляет видео по file_id."""
    token = settings.BOT_TOKEN
    payload = {"chat_id": chat_id, "video": video_file_id}
    if caption:
        payload["caption"] = caption[:1024]
    r = http_client.post(f"https://api.telegram.org/bot{token}/sendVideo", json=payload, timeout=60.0)
    r.raise_for_status()


def _run_ocr_on_image(image_bytes: bytes) -> str:
    """Распознаёт текст с изображения через LLM Vision (OpenRouter). Tesseract в коде не используется."""
    api_key = (settings.OPENROUTER_API_KEY or "").strip()
    if not api_key:
        logger.error(
            "OPENROUTER_API_KEY не задан. Добавьте ключ в .env в корне проекта и перезапустите воркер Celery."
        )
        raise ValueError("OPENROUTER_API_KEY is not set. Add it to .env and restart the Celery worker.")
    logger.info("OCR: вызов LLM Vision (OpenRouter), model=%s", settings.LLM_VISION_MODEL)
    from app.llm_ocr import extract_text_via_llm

    return extract_text_via_llm(
        image_bytes,
        api_key=settings.OPENROUTER_API_KEY,
        model=settings.LLM_VISION_MODEL,
        max_image_side=settings.LLM_MAX_IMAGE_SIZE,
        timeout=settings.LLM_REQUEST_TIMEOUT,
    )


def _page_text_sufficient(text: str, min_chars: int) -> bool:
    """
    Страница считается «лёгкой» (достаточно pypdf) только если символов >= min_chars
    и минимум 2 строки (одна строка — всегда в ИИ).
    """
    if len(text) < min_chars:
        return False
    lines = [s for s in text.strip().splitlines() if s.strip()]
    return len(lines) >= 2


def _pdf_analyze_pages(pdf_bytes: bytes) -> tuple[list[str], int]:
    """
    Извлекает текст pypdf по каждой странице (без вызова LLM).
    Возвращает (список строк по страницам, число страниц с текстом ниже порога — для LLM).
    """
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    pages = reader.pages
    total_pages = len(pages)
    max_pages = getattr(settings, "PDF_MAX_PAGES", 50) or 50
    if total_pages > max_pages:
        logger.warning("PDF has %s pages, capping to %s", total_pages, max_pages)
    pages = pages[:max_pages]

    min_chars = getattr(settings, "PDF_MIN_CHARS_PER_PAGE", 150) or 150
    texts: list[str] = []
    for page in pages:
        t = page.extract_text()
        texts.append((t or "").strip())
    llm_page_count = sum(1 for t in texts if not _page_text_sufficient(t, min_chars))
    for i, t in enumerate(texts, 1):
        decision = "pypdf" if _page_text_sufficient(t, min_chars) else "LLM"
        logger.info("PDF page %s: %s chars -> %s", i, len(t), decision)
    return texts, llm_page_count


def _run_llm_for_pdf_page(
    pdf_bytes: bytes, page_num: int, temp_dir: str
) -> str:
    """Рендерит одну страницу PDF в изображение и распознаёт через LLM. Возвращает текст или заглушку."""
    from pdf2image import convert_from_bytes
    from app.llm_ocr import extract_text_via_llm

    dpi = getattr(settings, "PDF_OCR_DPI", 200) or 200
    poppler_path = (getattr(settings, "POPPLER_PATH", None) or "").strip() or None
    try:
        kwargs: dict = {
            "dpi": dpi,
            "first_page": page_num,
            "last_page": page_num,
            "output_folder": temp_dir,
        }
        if poppler_path is not None:
            kwargs["poppler_path"] = poppler_path
        images = convert_from_bytes(pdf_bytes, **kwargs)
        if not images:
            return f"[Страница {page_num}: не удалось преобразовать]"
    except Exception as e:
        logger.warning("Failed to convert page %s: %s", page_num, e)
        err_msg = str(e)[:80]
        if "poppler" in err_msg.lower():
            logger.info("Poppler not found: set POPPLER_PATH in .env to poppler bin folder (Windows: poppler-windows on GitHub)")
        return f"[Страница {page_num}: ошибка конвертации — {err_msg}]"

    img = images[0]
    buf = BytesIO()
    img.save(buf, format="PNG")
    img_bytes = buf.getvalue()
    img.close()

    api_key = settings.OPENROUTER_API_KEY
    model = settings.LLM_VISION_MODEL
    max_side = settings.LLM_MAX_IMAGE_SIZE
    timeout = settings.LLM_REQUEST_TIMEOUT
    for attempt in range(3):
        try:
            text = extract_text_via_llm(
                img_bytes,
                api_key=api_key,
                model=model,
                max_image_side=max_side,
                timeout=timeout,
            )
            return text or f"[Страница {page_num}: текст не распознан]"
        except Exception as e:
            err_str = str(e).lower()
            if "rate" in err_str or "429" in err_str or "overloaded" in err_str:
                backoff = 2**attempt
                logger.warning("LLM rate limit, retry %s/%s in %ss", attempt + 1, 3, backoff)
                time.sleep(backoff)
            else:
                logger.exception("LLM OCR failed for page %s: %s", page_num, e)
                return f"[Страница {page_num}: ошибка — {str(e)[:100]}]"
    return f"[Страница {page_num}: превышено число попыток]"


def _process_pdf_hybrid(pdf_bytes: bytes, pypdf_texts: list[str]) -> str:
    """
    Гибридная сборка: по каждой странице — если pypdf дал достаточно символов и строк, берём его;
    иначе рендер в картинку + LLM (одна строка — всегда в ИИ).
    """
    min_chars = getattr(settings, "PDF_MIN_CHARS_PER_PAGE", 150) or 150
    try:
        import pdf2image  # noqa: F401 — check availability for _run_llm_for_pdf_page
    except Exception as e:
        logger.warning("pdf2image not available: %s", e)
        return "\n\n---\n\n".join(
            t if _page_text_sufficient(t, min_chars) else f"[Страница {i + 1}: pdf2image недоступен]"
            for i, t in enumerate(pypdf_texts)
        )

    import tempfile
    page_results: list[str] = []
    pypdf_used = 0
    llm_used = 0

    with tempfile.TemporaryDirectory() as temp_dir:
        for page_num, pypdf_text in enumerate(pypdf_texts, 1):
            if _page_text_sufficient(pypdf_text, min_chars):
                page_results.append(pypdf_text)
                pypdf_used += 1
            else:
                page_results.append(
                    _run_llm_for_pdf_page(pdf_bytes, page_num, temp_dir)
                )
                llm_used += 1

    logger.info("PDF hybrid: %s pypdf, %s LLM", pypdf_used, llm_used)
    return "\n\n---\n\n".join(page_results)


def _process_document_bytes(
    data: bytes,
    mime_type: str | None,
    file_name: str | None,
    pdf_preanalyzed: tuple[list[str], int] | None = None,
) -> tuple[bytes, str]:
    """
    Обрабатывает файл: фото → LLM OCR; PDF → гибрид (pypdf по страницам, при нехватке текста — LLM).
    pdf_preanalyzed: (pypdf_texts, llm_page_count) — результат _pdf_analyze_pages (для PDF вызывающий должен передать).
    Возвращает (результат в байтах, mime_type результата).
    """
    is_pdf = (mime_type and "pdf" in mime_type.lower()) or (
        file_name and file_name.lower().endswith(".pdf")
    )
    if is_pdf:
        if pdf_preanalyzed is not None:
            pypdf_texts, _ = pdf_preanalyzed
            text = _process_pdf_hybrid(data, pypdf_texts)
        else:
            pypdf_texts, _ = _pdf_analyze_pages(data)
            text = _process_pdf_hybrid(data, pypdf_texts)
    else:
        text = _run_ocr_on_image(data)
    return text.encode("utf-8"), "text/plain"


TG_MESSAGE_MAX_LENGTH = 4096


def _strip_markdown_from_ocr_text(text: str) -> str:
    """Убирает маркдаун-выделение (** и __) из ответа LLM, чтобы в Telegram не светились звёздочки."""
    if not text or not text.strip():
        return text
    import re
    # Удаляем ** и __ (жирный в Markdown), оставляя содержимое
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    t = re.sub(r"__(.+?)__", r"\1", t)
    return t


@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, document_id: int, file_id: str) -> None:
    """
    Скачивает файл из Telegram, запускает OCR/PDF, отправляет результат в чат:
    текстом (если ≤4096 символов) или одним .txt файлом.
    """
    total_deducted_limits = 1
    session = SyncSession()
    try:
        doc = session.execute(select(Document).where(Document.id == document_id).options(selectinload(Document.user))).scalar_one_or_none()
        if not doc:
            logger.warning("Document %s not found", document_id)
            return
        doc.status = "processing"
        session.commit()

        file_bytes = _download_telegram_file(file_id)

        is_pdf = (doc.mime_type and "pdf" in doc.mime_type.lower()) or (
            doc.file_name and doc.file_name.lower().endswith(".pdf")
        )
        pdf_preanalyzed: tuple[list[str], int] | None = None
        if is_pdf:
            from pypdf import PdfReader

            try:
                reader = PdfReader(BytesIO(file_bytes))
                total_pages = len(reader.pages)
            except Exception as e:
                logger.warning("Failed to read PDF to count pages: %s", e)
                total_pages = 1
            max_pages = getattr(settings, "PDF_MAX_PAGES", 50) or 50
            if total_pages > max_pages:
                _send_telegram_message(
                    doc.user.tg_id,
                    f"В вашем файле {total_pages} стр. Согласно ограничениям системы, будут обработаны только первые {max_pages} стр.",
                )

            pypdf_texts, llm_page_count = _pdf_analyze_pages(file_bytes)
            pdf_preanalyzed = (pypdf_texts, llm_page_count)

            if llm_page_count > 0:
                additional_limits_needed = llm_page_count - 1
                user_record = session.execute(
                    select(User).where(User.id == doc.user_id).options(selectinload(User.balance)).with_for_update()
                ).scalar_one()
                total_available = user_record.free_limits_remaining
                if user_record.balance:
                    total_available += user_record.balance.purchased_credits

                if total_available < additional_limits_needed:
                    user_record.free_limits_remaining += 1
                    doc.status = "error"
                    doc.error_message = "Not enough limits for PDF pages requiring AI"
                    session.commit()
                    _send_telegram_message(
                        doc.user.tg_id,
                        f"Для распознавания части страниц нужен ИИ. Требуется {llm_page_count} лимитов, у вас осталось {total_available + 1}. Пополните баланс или отправьте файл меньшего размера.",
                    )
                    return  # лимит уже возвращён, выходим

                remaining_to_deduct = additional_limits_needed
                if user_record.free_limits_remaining >= remaining_to_deduct:
                    user_record.free_limits_remaining -= remaining_to_deduct
                    remaining_to_deduct = 0
                else:
                    remaining_to_deduct -= user_record.free_limits_remaining
                    user_record.free_limits_remaining = 0
                if remaining_to_deduct > 0 and user_record.balance:
                    user_record.balance.purchased_credits -= remaining_to_deduct
                total_deducted_limits = llm_page_count
                session.commit()

        result_bytes, result_mime = _process_document_bytes(
            file_bytes, doc.mime_type, doc.file_name, pdf_preanalyzed=pdf_preanalyzed
        )
        text = result_bytes.decode("utf-8")
        text = _strip_markdown_from_ocr_text(text)

        doc.result_mime_type = result_mime
        doc.status = "done"
        doc.error_message = None
        session.commit()

        chat_id = doc.user.tg_id
        if len(text) <= TG_MESSAGE_MAX_LENGTH:
            _send_telegram_message(chat_id, text or "(Текст не распознан)", parse_mode=None)
        else:
            fname = f"Распознанный_текст_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt"
            _send_telegram_document(chat_id, text.encode("utf-8"), filename=fname)
            _send_telegram_message(chat_id, "Текст не поместился в сообщение — во вложении.")

        # Явное удаление конфиденциальных данных из памяти (152-ФЗ)
        del file_bytes
        del result_bytes
        del text
    except Exception as e:
        logger.exception("process_document_task failed: %s", e)
        session.rollback()
        doc = session.execute(
            select(Document).where(Document.id == document_id).options(selectinload(Document.user))
        ).scalar_one_or_none()
        if doc:
            doc.status = "error"
            doc.error_message = str(e)[:500]
            is_llm_or_config_error = (
                "openrouter" in str(e).lower()
                or "api_key" in str(e).lower()
                or "rate" in str(e).lower()
                or "429" in str(e)
            )
            if is_llm_or_config_error:
                session.execute(
                    update(User).where(User.id == doc.user_id).values(
                        free_limits_remaining=User.free_limits_remaining + total_deducted_limits
                    )
                )
            session.commit()
            try:
                if doc.user:
                    if is_llm_or_config_error:
                        _send_telegram_message(
                            doc.user.tg_id,
                            "Сервис распознавания временно недоступен. Обратитесь к администратору. Ваш лимит возвращён.",
                        )
                    else:
                        _send_telegram_message(
                            doc.user.tg_id,
                            "Не удалось обработать документ. Ваш лимит возвращён. Попробуйте позже или обратитесь в поддержку.",
                        )
            except Exception:
                pass
            if is_llm_or_config_error:
                return
        # Экспоненциальный backoff при rate limit / временных ошибках API
        countdown = min(2 ** self.request.retries, 60) if self.request.retries < self.max_retries else 60
        raise self.retry(exc=e, countdown=countdown)
    finally:
        session.close()


@celery_app.task
def broadcast_task(text: str = "", photo_file_id: str | None = None, video_file_id: str | None = None) -> None:
    """
    Рассылает сообщение всем пользователям (is_agreed_to_policy=True, is_banned=False).
    Один из: text, photo_file_id, video_file_id. Для фото/видео text — подпись.
    """
    import time
    session = SyncSession()
    try:
        result = session.execute(
            select(User.tg_id).where(User.is_agreed_to_policy).where(~User.is_banned)
        )
        tg_ids = [row[0] for row in result.fetchall()]
    finally:
        session.close()
    for chat_id in tg_ids:
        try:
            if photo_file_id:
                _send_telegram_photo(chat_id, photo_file_id, text)
            elif video_file_id:
                _send_telegram_video(chat_id, video_file_id, text)
            else:
                _send_telegram_message(chat_id, text or "(Пусто)", parse_mode=None)
        except Exception as e:
            logger.warning("broadcast to %s failed: %s", chat_id, e)
        time.sleep(0.05)


@celery_app.task
def reset_free_limits_task() -> None:
    """
    Периодическая задача: сброс бесплатных лимитов всем пользователям.
    Выставляется free_limits_remaining из настроек (БД или FREE_LIMITS_PER_MONTH) и free_limits_reset_at = now.
    """
    session = SyncSession()
    try:
        try:
            limit_str = get_setting_str_sync(
                session, "FREE_LIMITS_PER_MONTH", str(settings.FREE_LIMITS_PER_MONTH)
            )
        except Exception as e:
            logger.warning("get_setting_str_sync failed, using config: %s", e)
            limit_str = str(settings.FREE_LIMITS_PER_MONTH)
        try:
            limit = int(limit_str)
        except (ValueError, TypeError):
            limit = settings.FREE_LIMITS_PER_MONTH
        now = datetime.now(timezone.utc)
        result = session.execute(
            update(User).values(
                free_limits_remaining=limit,
                free_limits_reset_at=now,
            )
        )
        session.commit()
        rcount = getattr(result, "rowcount", None)
        count = rcount if rcount is not None and rcount >= 0 else "?"
        logger.info("reset_free_limits_task: updated %s users, limit=%s", count, limit)
    except Exception as e:
        logger.exception("reset_free_limits_task failed: %s", e)
        session.rollback()
    finally:
        session.close()


@celery_app.task
def cleanup_stale_documents_task() -> None:
    """
    Находит документы в pending/processing старше STALE_DOCUMENT_MINUTES минут,
    возвращает один лимит пользователю и помечает документ как error.
    """
    from datetime import timedelta

    session = SyncSession()
    try:
        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=STALE_DOCUMENT_MINUTES)
        result = session.execute(
            select(Document).where(
                Document.status.in_(["pending", "processing"]),
                Document.created_at < since,
            ).options(selectinload(Document.user))
        )
        stale_docs = result.scalars().all()
        if not stale_docs:
            return
        for doc in stale_docs:
            tg_id = doc.user.tg_id if doc.user else None
            try:
                user_row = session.execute(
                    select(User).where(User.id == doc.user_id).with_for_update()
                ).scalar_one_or_none()
                if user_row:
                    user_row.free_limits_remaining += 1
                doc.status = "error"
                doc.error_message = "Превышено время обработки. Лимит возвращён."
                session.commit()
                if tg_id:
                    try:
                        _send_telegram_message(
                            tg_id,
                            "Обработка файла не была завершена вовремя. Один лимит возвращён на ваш счёт. Попробуйте отправить файл снова.",
                            parse_mode=None,
                        )
                    except Exception as e:
                        logger.warning("Failed to notify user %s about stale doc: %s", tg_id, e)
                logger.info("cleanup_stale_documents: refunded limit for doc_id=%s user_id=%s", doc.id, doc.user_id)
            except Exception as e:
                logger.exception("cleanup_stale_documents failed for doc %s: %s", doc.id, e)
                session.rollback()
    except Exception as e:
        logger.exception("cleanup_stale_documents_task failed: %s", e)
        session.rollback()
    finally:
        session.close()
