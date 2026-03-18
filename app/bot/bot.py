import asyncio
import logging
import os
import sys
from pathlib import Path

from asgiref.sync import sync_to_async
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

import django

load_dotenv(BASE_DIR.parent / ".env")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from aiogram import Bot, Dispatcher
from aiogram.types import ChatMemberUpdated, Message
from scripts.models import Group

BOT_TOKEN = os.getenv("BOT_TOKEN")
WELCOME_MESSAGE = "Ассалому алейкум, я бот уведомлений Times School. Я буду сообщать вам новости 😊"
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. .env faylni tekshiring.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def _default_group_name(name: str | None) -> str:
    return name or "No name"


def _create_group(chat_id: int, name: str) -> tuple[Group, bool]:
    group = Group.objects.create(
        name=name,
        chat_id=chat_id,
        language="ru",
        is_active=True,
    )
    return group, True


def merge_group_records(old_chat_id: int, new_chat_id: int, name: str):
    old_group = Group.objects.filter(chat_id=old_chat_id).first()
    new_group = Group.objects.filter(chat_id=new_chat_id).first()

    if old_group and new_group:
        updated_fields = ["name", "is_active"]

        if not new_group.language and old_group.language:
            new_group.language = old_group.language
            updated_fields.append("language")

        if new_group.branch_id is None and old_group.branch_id is not None:
            new_group.branch = old_group.branch
            updated_fields.append("branch")

        new_group.name = name
        new_group.is_active = True
        new_group.save(update_fields=updated_fields)

        linked_scripts = list(old_group.scripts.all())
        if linked_scripts:
            new_group.scripts.add(*linked_scripts)

        old_group.delete()
        return new_group, False

    if old_group and not new_group:
        old_group.chat_id = new_chat_id
        old_group.name = name
        old_group.is_active = True
        old_group.save(update_fields=["chat_id", "name", "is_active"])
        return old_group, False

    if not old_group and new_group:
        new_group.name = name
        new_group.is_active = True
        new_group.save(update_fields=["name", "is_active"])
        return new_group, False

    return _create_group(new_chat_id, name)


def save_group_sync(chat_id: int, name: str):
    existing = Group.objects.filter(chat_id=chat_id).first()
    if existing:
        existing.name = name
        existing.is_active = True
        existing.save(update_fields=["name", "is_active"])
        return existing, False

    if str(chat_id).startswith("-100"):
        logger.warning(
            "New supergroup '%s' (%s) was saved without heuristic name-based merge",
            name,
            chat_id,
        )

    return _create_group(chat_id, name)


def _log_group_sync_result(action: str, group: Group, created: bool) -> None:
    state = "created" if created else "updated"
    logger.info("%s: %s group '%s' (%s)", action, state, group.name, group.chat_id)


def _became_active_member(event: ChatMemberUpdated) -> bool:
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    return old_status in ["left", "kicked"] and new_status in ["member", "administrator"]


async def _send_welcome_message(chat_id: int, chat_label: str) -> None:
    try:
        await bot.send_message(chat_id, WELCOME_MESSAGE)
        logger.info("Welcome message sent to '%s'", chat_label)
    except Exception:
        logger.exception("Failed to send welcome message to '%s'", chat_label)


async def _sync_group(chat_id: int, name: str, action: str):
    group, created = await sync_to_async(save_group_sync)(chat_id, name)
    _log_group_sync_result(action, group, created)
    return group, created


async def _handle_group_migration(old_chat_id: int, new_chat_id: int, name: str, action: str) -> None:
    group, created = await sync_to_async(merge_group_records)(old_chat_id, new_chat_id, name)
    _log_group_sync_result(action, group, created)


@dp.my_chat_member()
async def bot_added_to_group(event: ChatMemberUpdated):
    chat = event.chat
    if chat.type not in ["group", "supergroup"]:
        return

    if not _became_active_member(event):
        return

    chat_name = _default_group_name(chat.title)
    await _sync_group(chat.id, chat_name, "Group membership update")
    await _send_welcome_message(chat.id, chat.title or str(chat.id))


@dp.message()
async def group_message_handler(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return

    chat_name = _default_group_name(message.chat.title)

    if message.migrate_to_chat_id:
        await _handle_group_migration(
            message.chat.id,
            message.migrate_to_chat_id,
            chat_name,
            "Group migrated to supergroup",
        )
        return

    if message.migrate_from_chat_id:
        await _handle_group_migration(
            message.migrate_from_chat_id,
            message.chat.id,
            chat_name,
            "Group migrated from legacy id",
        )
        return

    await _sync_group(message.chat.id, chat_name, "Group message sync")


async def main():
    logger.info("Bot group synchronization polling started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
