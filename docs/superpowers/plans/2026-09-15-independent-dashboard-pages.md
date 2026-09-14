# Independent Dashboard Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** تبدیل داشبورد تک‌صفحه‌ای به یک workspace چندصفحه‌ای که نمای کلی، امروز، هفته، یادآوری‌ها، دسته‌بندی‌ها و گزارش‌ها هرکدام صفحهٔ مستقل داشته باشند.

**Architecture:** مسیرهای جدید FastAPI از کوئری‌های محدود به کاربر استفاده می‌کنند و قالب پایهٔ مشترک، سایدبار فعال و زیرمنوی دسته‌بندی را در همهٔ صفحات ارائه می‌دهد. نماهای ثبت‌ها از یک قالب فهرست مشترک استفاده می‌کنند تا فیلتر، زمان شمسی و عملیات ویرایش/حذف یکسان بماند.

**Tech Stack:** FastAPI، Jinja2، SQLAlchemy، SQLite، CSS موجود، pytest و مرورگر واقعی.

**Spec:** طرح تأییدشدهٔ گفت‌وگو در ۱۴۰۵/۰۶/۲۴ — workspace چندصفحه‌ای شخصی با مسیرهای مستقل.

## Global Constraints

- تمام داده‌ها فقط با `user.id` جاری خوانده و تغییر داده شوند.
- نمایش تاریخ و ساعت در رابط کاربری با قالب شمسی باقی بماند.
- طراحی راست‌چین، واکنش‌گرا و سازگار با سایدبار فعلی باشد.
- عملیات یادآوری و ویرایش/حذف رکوردها بدون تغییر در کنترل دسترسی فعلی انجام شوند.

### Task 1: تعریف مسیرهای مستقل و تست دسترسی

**Files:**
- Modify: `app/web.py`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write failing tests** برای مسیرهای `/today`، `/week`، `/reminders` و `/categories/{category}` و redirect کاربر بدون نشست.
- [ ] **Step 2: Run tests and confirm failure** با `.venv/bin/pytest -q tests/test_web.py`.
- [ ] **Step 3: Add routes** با context محدود به کاربر و پارامترهای period/category.
- [ ] **Step 4: Run focused tests and confirm pass**.

### Task 2: قالب‌های مستقل workspace

**Files:**
- Create: `app/templates/records.html`
- Create: `app/templates/reminders.html`
- Create: `app/templates/overview.html`
- Modify: `app/templates/base.html`

- [ ] **Step 1: Add template assertions** برای عنوان صفحه، آیتم فعال سایدبار و لینک‌های مستقل.
- [ ] **Step 2: Run focused tests and confirm failure**.
- [ ] **Step 3: Build templates** با timeline ثبت‌ها، فهرست یادآوری‌ها و نمای کلی کم‌کارت.
- [ ] **Step 4: Run tests and confirm pass**.

### Task 3: بازطراحی CSS و اتصال صفحات

**Files:**
- Modify: `app/static/style.css`
- Modify: `app/templates/dashboard.html`
- Modify: `app/templates/report.html`
- Modify: `app/templates/settings.html`

- [ ] **Step 1: Add CSS/HTML behavior tests** برای حذف وابستگی نمای کلی به کارت‌های آماری و وجود nav مستقل.
- [ ] **Step 2: Run tests and confirm failure**.
- [ ] **Step 3: Apply workspace layout** شامل سربرگ، timeline، پنل گزارش، responsive mobile و state فعال.
- [ ] **Step 4: Run pytest, ruff and diff checks**.

### Task 4: کنترل مرورگر و انتشار

- [ ] **Step 1:** اجرای تست مرورگر در desktop و mobile برای مسیرهای عمومی و احراز‌شده.
- [ ] **Step 2:** ساخت Docker image و بررسی health endpoint.
- [ ] **Step 3:** commit و push به `master`.
