# Production Deploy Checklist

## 1. Server tayyorlash
- Ubuntu server tayyor bo'lsin.
- `docker` va `docker compose` o'rnatilgan bo'lsin.
- Firewall yoqilgan bo'lsin.
- Faqat kerakli portlar ochiq bo'lsin: `80`.
- `5432` va `6379` tashqariga ochilmasin.

## 2. Kodni serverga olib chiqish
- Project fayllarini serverga ko'chiring.
- Project papkaga kiring.
- `docker-compose.prod.yml`, `.env.production`, `deploy/nginx/default.conf` joyida ekanini tekshiring.

## 3. .env tayyorlash
- `.env.production` faylni serverda `.env` nomiga ko'chiring.
- Quyidagilarni haqiqiy qiymatlarga almashtiring:
  - `BOT_TOKEN`
  - `SERVER_IP`
  - `DJANGO_SECRET_KEY` agar o'zgartirmoqchi bo'lsangiz
  - `POSTGRES_PASSWORD` agar o'zgartirmoqchi bo'lsangiz
- `DJANGO_DEBUG=False` ekanini tasdiqlang.

## 4. Muhim env qiymatlar
- `DJANGO_ALLOWED_HOSTS=SERVER_IP`
- `DJANGO_CSRF_TRUSTED_ORIGINS=http://SERVER_IP`
- `USE_POSTGRES=True`
- `POSTGRES_HOST=postgres`
- `REDIS_HOST=redis`

## 5. Birinchi ishga tushirish
```bash
docker compose -f docker-compose.prod.yml --env-file .env up --build -d
```

## 6. Holatni tekshirish
```bash
docker compose -f docker-compose.prod.yml ps
```

Loglar:
```bash
docker compose -f docker-compose.prod.yml logs -f web
```
```bash
docker compose -f docker-compose.prod.yml logs -f worker
```
```bash
docker compose -f docker-compose.prod.yml logs -f beat
```
```bash
docker compose -f docker-compose.prod.yml logs -f bot
```
```bash
docker compose -f docker-compose.prod.yml logs -f nginx
```

## 7. Migratsiya va static
- `web` container start bo'lganda `migrate` va `collectstatic` avtomatik ishlaydi.
- `web` logida xato yo'qligini tekshiring.

## 8. Admin panelni tekshirish
- Brauzerda oching: `http://SERVER_IP/admin/`
- Login qiling.
- `Branches`, `Groups`, `Scripts` ochilishini tekshiring.

## 9. Botni tekshirish
- Bot logida polling ishlayotganini ko'ring.
- Test groupga botni qo'shib ko'ring.
- Welcome message kelishini tekshiring.

## 10. Schedulerni tekshirish
- Admin paneldan 2-3 daqiqa keyinga test script yarating.
- `worker` va `beat` loglarini kuzating.
- Xabar groupga borganini tekshiring.

## 11. Backup
- PostgreSQL backup strategiya qiling.
- Minimum variant:
```bash
docker exec -t bot_postgres_prod pg_dump -U telegram_bot telegram_bot > backup.sql
```
- Media fayllar backupini ham qiling.

## 12. Xavfsizlik
- Productiondan oldin bot tokenni rotate qiling.
- Admin user uchun kuchli parol qo'ying.
- Keyingi bosqichda HTTPS qo'shing.

## 13. Update qilish
```bash
docker compose -f docker-compose.prod.yml --env-file .env down
```
```bash
docker compose -f docker-compose.prod.yml --env-file .env up --build -d
```

## 14. Muammolar bo'lsa
- `web` ochilmasa: `web` va `nginx` logini tekshiring.
- Admin save ishlamasa: `DJANGO_ALLOWED_HOSTS` va `DJANGO_CSRF_TRUSTED_ORIGINS` ni tekshiring.
- Script yuborilmasa: `worker`, `beat`, `bot` loglarini tekshiring.
