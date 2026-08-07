# OLX Tracker Bot 🤖

Telegram-бот для автоматичного відстеження статистики оголошень на **OLX.ua**.  
Розроблено на **Python 3.11+**, **aiogram 3.x**, **SQLAlchemy async + asyncpg**.  
Оптимізовано для деплою на **Railway.app**.

---

## Функціонал

| Команда | Опис |
|---------|------|
| `/start` | Вітання та автореєстрація в БД |
| `/add <назва> <url>` | Додати OLX-оголошення до відстеження |
| `/list` | Список усіх відстежуваних оголошень |
| `/stats` | Поточна статистика + динаміка (±) |
| `/delete` | Видалення через inline-кнопки |

**Авто-сповіщення** — бот надсилає повідомлення при виявленні росту переглядів, обраного або кліків на телефон.

**Планувальник** — перевірка кожні 2 години з затримкою 15 сек між оголошеннями.

---

## Структура проєкту

```
OLX/
├── main.py                  # Точка входу
├── config.py                # Змінні оточення
├── requirements.txt
├── Procfile                 # Railway: worker
├── railway.toml             # Railway config
├── database/
│   ├── models.py            # SQLAlchemy моделі: users, items, stats
│   └── repository.py        # Async CRUD
├── scraper/
│   └── olx.py              # OLX парсер (httpx + multi-strategy)
├── bot/
│   ├── keyboards.py         # Inline-клавіатури
│   ├── middlewares.py       # DB-ін'єкція в хендлери
│   └── handlers/
│       ├── start.py         # /start
│       ├── items.py         # /add, /list, /delete
│       └── stats.py         # /stats
└── scheduler/
    └── tasks.py             # APScheduler (2 год інтервал)
```

---

## Локальний запуск

### 1. Клонуйте або завантажте проєкт

```bash
cd OLX
```

### 2. Встановіть залежності

```bash
pip install -r requirements.txt
```

### 3. Налаштуйте змінні оточення

Створіть файл `.env` у корені:

```env
BOT_TOKEN=8810467336:AAGv-TAh9sfJVRvs1DvoN4MipAc_RFNkw5U
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/olx_tracker
LOG_LEVEL=INFO
CHECK_INTERVAL_HOURS=2
DELAY_BETWEEN_ITEMS_SEC=15
```

> **Локальний PostgreSQL:**
> ```sql
> CREATE DATABASE olx_tracker;
> ```

### 4. Запустіть бота

```bash
python main.py
```

Таблиці створюються **автоматично** при першому запуску.

---

## Деплой на Railway.app

### Крок 1 — Створіть проєкт на Railway

1. Перейдіть на [railway.app](https://railway.app) та увійдіть через GitHub.
2. Натисніть **New Project → Deploy from GitHub repo** і оберіть ваш репозиторій.

### Крок 2 — Додайте PostgreSQL

1. У вашому проєкті натисніть **+ Add Service → PostgreSQL**.
2. Railway автоматично встановить змінну `DATABASE_URL` у вашому сервісі.

### Крок 3 — Встановіть змінні оточення

У Railway → вкладка **Variables** додайте:

```
BOT_TOKEN=<ваш токен>
```

> `DATABASE_URL` Railway підставляє автоматично з PostgreSQL сервісу.

### Крок 4 — Деплой

Railway автоматично виявить `Procfile` та запустить:

```
worker: python main.py
```

---

## Змінні оточення

| Змінна | За замовчуванням | Опис |
|--------|-----------------|------|
| `BOT_TOKEN` | `8810467336:...` | Токен Telegram-бота |
| `DATABASE_URL` | `postgresql+asyncpg://localhost/olx_tracker` | URL підключення до PostgreSQL |
| `CHECK_INTERVAL_HOURS` | `2` | Інтервал між перевірками (годин) |
| `DELAY_BETWEEN_ITEMS_SEC` | `15` | Затримка між запитами до OLX (секунд) |
| `LOG_LEVEL` | `INFO` | Рівень логування (`DEBUG`, `INFO`, `WARNING`) |

---

## База даних

### Таблиця `users`

| Поле | Тип | Опис |
|------|-----|------|
| `id` | BIGINT PK | Telegram user_id |
| `username` | VARCHAR | @username |
| `first_name` | VARCHAR | Ім'я |
| `created_at` | TIMESTAMP | Дата реєстрації |

### Таблиця `items`

| Поле | Тип | Опис |
|------|-----|------|
| `id` | INT PK | Авто-ID |
| `user_id` | BIGINT FK | Посилання на users |
| `olx_url` | VARCHAR | Посилання на OLX |
| `title` | VARCHAR | Назва оголошення |
| `created_at` | TIMESTAMP | Дата додавання |

### Таблиця `stats`

| Поле | Тип | Опис |
|------|-----|------|
| `id` | INT PK | Авто-ID |
| `item_id` | INT FK | Посилання на items |
| `views_count` | INT | Перегляди |
| `favorites_count` | INT | Обране |
| `phone_clicks_count` | INT | Кліки на телефон |
| `timestamp` | TIMESTAMP | Час зняття статистики |

---

## Парсер OLX

Використовує **чотири стратегії** (від точнішої до fallback):

1. **`window.__REDUX_STATE__`** — JSON-об'єкт, вбудований у HTML (основне джерело).
2. **`window.__INITIAL_STATE__`** — альтернативний стейт.
3. **JSON-LD** (`application/ld+json`) — структуровані мета-дані.
4. **HTML regex** — пошук числових патернів у HTML тексті.

При отриманні **403/429** — запит логується, бот продовжує роботу без краша.

---

## Початкові оголошення (автосів)

При першому запуску в БД автоматично додаються:

1. **Колаген 464г** — California Gold Premium Collagen
2. **Rayban Meta** — Ray-Ban Meta Wayfarer Gen 2
3. **Gymshark Mesh** — Gymshark oversized футболка

Вони відстежуються від імені системного користувача (ID=0) і є доступними в планувальнику одразу після старту.

---

## Вимоги

- Python **3.11+**
- PostgreSQL **14+**
- Інтернет-доступ для запитів до OLX хуй
- 

---

## Ліцензія

MIT — вільне використання та модифікація.
