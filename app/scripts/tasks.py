import os
import asyncio
from celery import shared_task
from dotenv import load_dotenv
from django.utils import timezone
from aiogram import Bot

from .models import Script

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")


async def send_telegram_messages(messages):
    bot = Bot(token=TOKEN)
    try:
        for item in messages:
            await bot.send_message(item["chat_id"], item["text"])
            print(f"[SENT OK] -> {item['group_name']}")
    finally:
        await bot.session.close()


@shared_task
def send_scheduled_scripts():
    now = timezone.localtime()
    print(f"[TASK START] now = {now}")

    scripts = Script.objects.filter(
        is_active=True
    ).prefetch_related("groups")

    print(f"[TASK INFO] scripts count = {scripts.count()}")

    for script in scripts:
        send_time = timezone.localtime(script.send_time)

        same_day = now.day == send_time.day
        same_hour = now.hour == send_time.hour
        same_minute = now.minute == send_time.minute

        print(
            f"[SCRIPT] id={script.id}, title={script.title}, "
            f"repeat_type={script.repeat_type}, send_time={send_time}, "
            f"last_sent_at={script.last_sent_at}"
        )
        print(
            f"[CHECK] same_day={same_day}, same_hour={same_hour}, same_minute={same_minute}"
        )

        should_send = False

        if script.repeat_type == "once":
            same_year = now.year == send_time.year
            same_month = now.month == send_time.month

            print(
                f"[ONCE CHECK] same_year={same_year}, same_month={same_month}"
            )

            if same_year and same_month and same_day and same_hour and same_minute:
                if script.last_sent_at:
                    print(f"[SKIP] Once script already sent: {script.title}")
                    continue
                should_send = True

        elif script.repeat_type == "monthly":
            if same_day and same_hour and same_minute:
                if script.last_sent_at:
                    last_sent = timezone.localtime(script.last_sent_at)
                    if last_sent.year == now.year and last_sent.month == now.month:
                        print(f"[SKIP] Already sent this month: {script.title}")
                        continue
                should_send = True

        if not should_send:
            continue

        messages_to_send = []

        for group in script.groups.all():
            if not group.is_active:
                print(f"[SKIP GROUP] inactive -> {group.name}")
                continue

            if not group.language:
                print(f"[SKIP GROUP] language not set -> {group.name}")
                continue

            text = script.text_uz if group.language == "uz" else script.text_ru

            if not text:
                print(f"[SKIP GROUP] text empty -> {group.name}")
                continue

            print(
                f"[SEND TRY] script={script.title}, "
                f"group={group.name}, language={group.language}, "
                f"chat_id={group.chat_id}"
            )

            messages_to_send.append({
                "chat_id": group.chat_id,
                "text": text,
                "group_name": group.name,
            })

        if not messages_to_send:
            print(f"[SKIP] No valid groups for script: {script.title}")
            continue

        try:
            asyncio.run(send_telegram_messages(messages_to_send))
            script.last_sent_at = now
            script.save(update_fields=["last_sent_at"])
            print(f"[DONE] last_sent_at updated for {script.title}")
        except Exception as e:
            print(f"[TASK ERROR] {script.title}: {e}")

    print("[TASK END]")