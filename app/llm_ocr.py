"""
Распознавание текста с изображений через LLM Vision API (OpenRouter).
Ресайз картинок для экономии токенов, строгий system prompt для OCR без галлюцинаций.
"""
from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — высокоточный OCR-инструмент. Твоя единственная задача: извлечь весь текст с изображения дословно.

Правила:
- Возвращай СТРОГО только распознанный текст, без приветствий, пояснений и комментариев.
- Сохраняй абзацы, списки и структуру (переносы строк). Таблицы можно оформить в Markdown.
- Математические и физические формулы переводи в LaTeX (например \frac{a}{b}, x^2).
- Игнорируй водяные знаки, логотипы, обрывки фонового текста и артефакты, не относящиеся к основному содержанию.
- Исправляй очевидные опечатки распознавания (например «овтетственность» → «ответственность»), но не меняй смысл и термины.
- Языки: русский и английский. Не переводи текст, выводи в оригинале."""


def prepare_image_for_llm(image_bytes: bytes, max_side: int = 2048, jpeg_quality: int = 88) -> bytes:
    """
    Уменьшает изображение до max_side по большей стороне и конвертирует в JPEG.
    Возвращает байты JPEG для последующего base64.
    """
    from PIL import Image

    if not image_bytes or len(image_bytes) < 100:
        raise ValueError("Изображение пустое или слишком маленькое")
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception as e:
        logger.warning("Не удалось открыть изображение: %s", e)
        raise ValueError(f"Не удалось прочитать изображение: {e!s}") from e
    w, h = img.size
    if max(w, h) <= max_side:
        out = BytesIO()
        img.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
        return out.getvalue()
    scale = max_side / max(w, h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    resampling = getattr(Image, "Resampling", Image).LANCZOS
    img = img.resize((new_w, new_h), resampling)
    out = BytesIO()
    img.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
    return out.getvalue()


def image_bytes_to_base64_data_url(image_bytes: bytes, max_side: int = 2048) -> str:
    """Подготавливает картинку (ресайз) и возвращает data URL для API: data:image/jpeg;base64,..."""
    jpeg_bytes = prepare_image_for_llm(image_bytes, max_side=max_side)
    b64 = base64.standard_b64encode(jpeg_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def extract_text_via_llm(
    image_bytes: bytes,
    *,
    api_key: str,
    model: str,
    max_image_side: int = 2048,
    timeout: int = 90,
) -> str:
    """
    Синхронный вызов OpenRouter Vision API для извлечения текста с изображения.
    Используется в Celery-воркере.
    """
    if not api_key or not api_key.strip():
        raise ValueError("OPENROUTER_API_KEY is not set")
    from openai import OpenAI

    logger.info("OpenRouter: отправка запроса, model=%s", model)
    data_url = image_bytes_to_base64_data_url(image_bytes, max_side=max_image_side)
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key.strip(),
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Извлеки весь текст с этого изображения."},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        max_tokens=4096,
        temperature=0.0,
        timeout=timeout,
    )
    choice = response.choices[0] if response.choices else None
    if not choice or not choice.message or not choice.message.content:
        return ""
    return (choice.message.content or "").strip()
