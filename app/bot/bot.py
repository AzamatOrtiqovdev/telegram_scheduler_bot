import asyncio
import os
import sys
from pathlib import Path

from asgiref.sync import sync_to_async
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

import django

load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from aiogram import Bot, Dispatcher
from aiogram.types import ChatMemberUpdated, Message
from scripts.models import Group

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. .env faylni tekshiring.")

bot = Bot(token=TOKEN)
dp = Dispatcher()


def merge_group_records(old_chat_id: int, new_chat_id: int, name: str):
    """
    Eski oddiy group id sini yangi supergroup id ga birlashtiradi.
    """
    old_group = Group.objects.filter(chat_id=old_chat_id).first()
    new_group = Group.objects.filter(chat_id=new_chat_id).first()

    if old_group and new_group:
        # Ikkalasi ham bo'lsa, eski yozuvni o'chirib, yangisini saqlaymiz
        # Til yo'qolib ketmasligi uchun kerak bo'lsa ko'chirib o'tkazamiz
        if not new_group.language and old_group.language:
            new_group.language = old_group.language
        new_group.name = name
        new_group.is_active = True
        new_group.save()

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

    group = Group.objects.create(
        name=name,
        chat_id=new_chat_id,
        language="ru",
        is_active=True,
    )
    return group, True


def save_group_sync(chat_id: int, name: str):
    """
    Oddiy saqlash / yangilash.
    """
    existing = Group.objects.filter(chat_id=chat_id).first()
    if existing:
        existing.name = name
        existing.is_active = True
        existing.save(update_fields=["name", "is_active"])
        return existing, False

    # Agar yangi id supergroup bo'lsa va shu nomli eski oddiy group bo'lsa, birlashtiramiz
    if str(chat_id).startswith("-100"):
        old_group_same_name = (
            Group.objects.filter(name=name)
            .exclude(chat_id=chat_id)
            .exclude(chat_id__startswith="-100")
            .first()
        )

        if old_group_same_name:
            old_group_same_name.chat_id = chat_id
            old_group_same_name.is_active = True
            old_group_same_name.save(update_fields=["chat_id", "is_active"])
            return old_group_same_name, False

    group = Group.objects.create(
        name=name,
        chat_id=chat_id,
        language="ru",
        is_active=True,
    )
    return group, True


@dp.my_chat_member()
async def bot_added_to_group(event: ChatMemberUpdated):
    chat = event.chat

    if chat.type not in ["group", "supergroup"]:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    became_member = old_status in ["left", "kicked"] and new_status in ["member", "administrator"]
    became_admin = old_status == "left" and new_status == "administrator"

    if became_member or became_admin:
        group, created = await sync_to_async(save_group_sync)(
            chat.id,
            chat.title or "No name"
        )

        if created:
            print(f"[NEW GROUP SAVED] {group.name} | {group.chat_id}")
        else:
            print(f"[GROUP UPDATED] {group.name} | {group.chat_id}")


@dp.message()
async def group_message_handler(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        return

    # Muhim: oddiy group -> supergroup migratsiya update
    if message.migrate_to_chat_id:
        group, created = await sync_to_async(merge_group_records)(
            message.chat.id,
            message.migrate_to_chat_id,
            message.chat.title or "No name"
        )

        if created:
            print(f"[GROUP MIGRATED - CREATED] {group.name} | {group.chat_id}")
        else:
            print(f"[GROUP MIGRATED - MERGED] {group.name} | {group.chat_id}")
        return

    if message.migrate_from_chat_id:
        group, created = await sync_to_async(merge_group_records)(
            message.migrate_from_chat_id,
            message.chat.id,
            message.chat.title or "No name"
        )

        if created:
            print(f"[GROUP MIGRATED FROM - CREATED] {group.name} | {group.chat_id}")
        else:
            print(f"[GROUP MIGRATED FROM - MERGED] {group.name} | {group.chat_id}")
        return

    group, created = await sync_to_async(save_group_sync)(
        message.chat.id,
        message.chat.title or "No name"
    )

    if created:
        print(f"[GROUP SAVED FROM MESSAGE] {group.name} | {group.chat_id}")
    else:
        print(f"[GROUP UPDATED FROM MESSAGE] {group.name} | {group.chat_id}")


async def main():
    print("Bot guruhlarni kuzatyapti...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())