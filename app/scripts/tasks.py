import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from aiogram import Bot
from aiogram.types import FSInputFile, InputMediaPhoto
from celery import shared_task
from django.utils import timezone
from dotenv import load_dotenv
from PIL import Image

from .models import Script

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
logger = logging.getLogger(__name__)


def _truncate_to_minute(value):
    return value.replace(second=0, microsecond=0)


def _is_same_or_past_minute(now, scheduled_time) -> bool:
    return _truncate_to_minute(now) >= _truncate_to_minute(scheduled_time)


def _has_reached_scheduled_clock_time(now, scheduled_time) -> bool:
    current_minute = (now.hour, now.minute)
    scheduled_minute = (scheduled_time.hour, scheduled_time.minute)
    return current_minute >= scheduled_minute


TELEGRAM_MAX_PHOTO_DIMENSION_SUM = 10000


def _needs_photo_resize(width: int, height: int) -> bool:
    return width + height > TELEGRAM_MAX_PHOTO_DIMENSION_SUM


def _normalized_photo_path(image_path: str, temp_dir: str) -> str:
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        width, height = image.size

        if not _needs_photo_resize(width, height):
            return image_path

        scale = (TELEGRAM_MAX_PHOTO_DIMENSION_SUM - 1) / (width + height)
        resized = image.resize((max(1, int(width * scale)), max(1, int(height * scale))))
        normalized_path = Path(temp_dir) / f"normalized_{Path(image_path).stem}_{uuid4().hex}.jpg"
        resized.save(normalized_path, format="JPEG", quality=95)
        logger.info(
            "Resized image '%s' from %sx%s to %sx%s for Telegram photo constraints",
            image_path,
            width,
            height,
            resized.width,
            resized.height,
        )
        return str(normalized_path)


def _normalized_photo_paths(image_paths: list[str], temp_dir: str) -> list[str]:
    return [_normalized_photo_path(image_path, temp_dir) for image_path in image_paths]


async def send_telegram_messages(messages: list[dict[str, Any]]) -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured")

    bot = Bot(token=BOT_TOKEN)
    try:
        with tempfile.TemporaryDirectory(prefix="telegram-script-images-") as temp_dir:
            for message in messages:
                image_paths = _normalized_photo_paths(message["image_paths"], temp_dir)
                text = message["text"] or ""

                if len(image_paths) > 1:
                    media = []
                    for index, image_path in enumerate(image_paths):
                        media_item = InputMediaPhoto(media=FSInputFile(image_path))
                        if index == 0 and text:
                            media_item.caption = text
                        media.append(media_item)

                    await bot.send_media_group(chat_id=message["chat_id"], media=media)
                    logger.info("Sent %s photos to group '%s'", len(image_paths), message["group_name"])
                elif image_paths:
                    await bot.send_photo(
                        chat_id=message["chat_id"],
                        photo=FSInputFile(image_paths[0]),
                        caption=text,
                    )
                    logger.info("Sent photo to group '%s'", message["group_name"])
                elif text:
                    await bot.send_message(
                        chat_id=message["chat_id"],
                        text=text,
                    )
                    logger.info("Sent text to group '%s'", message["group_name"])
    finally:
        await bot.session.close()


def _was_sent_today(script: Script, now) -> bool:
    if not script.last_sent_at:
        return False

    last_sent = timezone.localtime(script.last_sent_at)
    return last_sent.date() == now.date()


def _was_sent_this_month(script: Script, now) -> bool:
    if not script.last_sent_at:
        return False

    last_sent = timezone.localtime(script.last_sent_at)
    return last_sent.year == now.year and last_sent.month == now.month


def _is_due_once(script: Script, now, send_time) -> bool:
    return (
        now.year == send_time.year
        and now.month == send_time.month
        and now.day == send_time.day
        and now.hour == send_time.hour
        and now.minute == send_time.minute
        and not script.last_sent_at
    )


def _is_due_monthly(script: Script, now, send_time) -> bool:
    return (
        now.day == send_time.day
        and _has_reached_scheduled_clock_time(now, send_time)
        and not _was_sent_this_month(script, now)
    )


def _is_due_daily(script: Script, now, send_time) -> bool:
    return _has_reached_scheduled_clock_time(now, send_time) and not _was_sent_today(script, now)


def _should_send_script(script: Script, now) -> bool:
    send_time = timezone.localtime(script.send_time)

    if script.repeat_type == "once":
        return _is_due_once(script, now, send_time)
    if script.repeat_type == "monthly":
        return _is_due_monthly(script, now, send_time)
    if script.repeat_type == "daily":
        return _is_due_daily(script, now, send_time)

    logger.warning("Unsupported repeat_type '%s' for script '%s'", script.repeat_type, script.title)
    return False


def _resolve_group_text(script: Script, group) -> str | None:
    has_uz_text = bool(script.text_uz and script.text_uz.strip())
    has_ru_text = bool(script.text_ru and script.text_ru.strip())

    if not group.is_active:
        logger.debug("Skipping inactive group '%s'", group.name)
        return None

    if not group.language:
        logger.debug("Skipping group '%s' because language is not set", group.name)
        return None

    if group.language == "uz":
        if has_uz_text:
            return script.text_uz
        logger.debug("Skipping group '%s' because Uzbek text is missing", group.name)
        return None

    if group.language == "ru":
        if has_ru_text:
            return script.text_ru
        logger.debug("Skipping group '%s' because Russian text is missing", group.name)
        return None

    logger.debug("Skipping group '%s' because language '%s' is unsupported", group.name, group.language)
    return None


def _build_messages(script: Script) -> list[dict[str, Any]]:
    image_paths = script.get_image_paths()
    messages: list[dict[str, Any]] = []

    for group in script.get_target_groups():
        text = _resolve_group_text(script, group)
        if not text and not image_paths:
            logger.debug("Skipping group '%s' because script has no suitable content", group.name)
            continue

        if not text and image_paths and group.language not in {"uz", "ru"}:
            continue

        if text is None and image_paths and group.language in {"uz", "ru"}:
            text = ""

        messages.append(
            {
                "chat_id": group.chat_id,
                "text": text,
                "group_name": group.name,
                "image_paths": image_paths,
            }
        )

    return messages


@shared_task
def send_scheduled_scripts() -> None:
    now = timezone.localtime()
    scripts = list(
        Script.objects.filter(is_active=True).prefetch_related(
            "branches__groups",
            "groups",
            "images",
        )
    )

    logger.info("Scheduled script task started at %s with %s active scripts", now, len(scripts))

    for script in scripts:
        if not _should_send_script(script, now):
            continue

        messages_to_send = _build_messages(script)
        if not messages_to_send:
            logger.info("Skipping script '%s' because it has no valid target groups", script.title)
            continue

        try:
            asyncio.run(send_telegram_messages(messages_to_send))
            script.last_sent_at = now
            script.save(update_fields=["last_sent_at"])
            logger.info("Updated last_sent_at for script '%s'", script.title)
        except Exception:
            logger.exception("Failed to send scheduled script '%s'", script.title)

    logger.info("Scheduled script task finished")
