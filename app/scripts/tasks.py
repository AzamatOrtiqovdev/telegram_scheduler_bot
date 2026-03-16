import asyncio
import logging
import os
from typing import Any

from aiogram import Bot
from aiogram.types import FSInputFile
from celery import shared_task
from django.utils import timezone
from dotenv import load_dotenv

from .models import Script

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
logger = logging.getLogger(__name__)


async def send_telegram_messages(messages: list[dict[str, Any]]) -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured")

    bot = Bot(token=BOT_TOKEN)
    try:
        for message in messages:
            if message["image_path"]:
                photo = FSInputFile(message["image_path"])
                await bot.send_photo(
                    chat_id=message["chat_id"],
                    photo=photo,
                    caption=message["text"] or "",
                )
                logger.info("Sent photo to group '%s'", message["group_name"])
            else:
                await bot.send_message(
                    chat_id=message["chat_id"],
                    text=message["text"] or "",
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
        and now.hour == send_time.hour
        and now.minute == send_time.minute
        and not _was_sent_this_month(script, now)
    )


def _is_due_daily(script: Script, now, send_time) -> bool:
    return now.hour == send_time.hour and now.minute == send_time.minute and not _was_sent_today(script, now)


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
    image_path = script.image.path if script.image else None
    messages: list[dict[str, Any]] = []

    for group in script.get_target_groups():
        text = _resolve_group_text(script, group)
        if not text and not image_path:
            logger.debug("Skipping group '%s' because script has no suitable content", group.name)
            continue

        if not text and image_path and group.language not in {"uz", "ru"}:
            continue

        if text is None and image_path and group.language in {"uz", "ru"}:
            text = ""

        messages.append(
            {
                "chat_id": group.chat_id,
                "text": text,
                "group_name": group.name,
                "image_path": image_path,
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
