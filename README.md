# صندوقچه شخصی

دستیار خصوصی فارسی برای ثبت پیام‌های صوتی و متنی در گفت‌وگوی خصوصی بله. برنامه
پیام را با AvalAI رونویسی و دسته‌بندی می‌کند، موارد قابل اقدام را با تاریخ شمسی
ذخیره می‌کند، یادآوری می‌فرستد و گزارش روزانه/هفتگی می‌سازد.

## اجرای محلی

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
# متغیرهای .env را کامل کن
.venv/bin/uvicorn app.main:app --reload
```

## متغیرهای محیطی

حداقل این موارد لازم‌اند: `BALE_BOT_TOKEN`، `BALE_WEBHOOK_SECRET`،
`AVALAI_API_KEY`، `AVALAI_TRANSCRIBE_MODEL`، `AVALAI_TEXT_MODEL`،
`SESSION_SECRET`، `APP_BASE_URL` و `DATABASE_PATH`.

`SESSION_SECRET` و `BALE_WEBHOOK_SECRET` را با مقدار تصادفی طولانی بساز. کلیدها
را در git یا فایل image قرار نده.

## Coolify

1. یک سرویس Docker از همین repository و branch `master` بساز.
2. دامنه `self.araz.me` را به پورت داخلی `8000` وصل کن و HTTPS را فعال کن.
3. یک volume پایدار به `/data` متصل کن.
4. متغیرهای `.env.example` را در بخش Environment Variables وارد کن؛ مسیر
   `DATABASE_PATH` را `/data/self.sqlite3` بگذار.
5. بعد از deploy، webhook بله را با secret تنظیم کن:

```bash
curl -X POST "https://tapi.bale.ai/bot${BALE_BOT_TOKEN}/setWebhook" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://self.araz.me/bale/webhook/'"${BALE_WEBHOOK_SECRET}"'"}'
```

در Coolify فقط یک replica اجرا کن؛ scheduler این نسخه داخل همان process است.
در مقیاس چند replica باید worker و قفل توزیع‌شده جدا اضافه شود.

## رفتار حریم خصوصی

- فقط پیام‌های `private` بله پردازش می‌شوند.
- همهٔ رکوردها با `user_id` صاحب بله query می‌شوند.
- لینک داشبورد ۱۰ دقیقه اعتبار دارد و فقط یک‌بار مصرف است؛ سپس session امن
  ساخته می‌شود.
- صوت خام روی دیسک ذخیره نمی‌شود و فقط در حافظه برای رونویسی استفاده می‌شود.
- برنامه هیچ پرداخت، ارسال پیام به دیگران یا عملیات خارجی را خودکار انجام
  نمی‌دهد.

## تست

```bash
.venv/bin/pytest -q
.venv/bin/ruff check app tests
```
