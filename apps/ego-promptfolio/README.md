# Ego Promptfolio

Портfolio-сайт на **Flask**: главная страница, кейсы, форма обратной связи и админ-панель для управления заявками.

## Требования

- Python 3.10+

## Первый запуск

```powershell
Set-Location C:\Dev\oss\ego-faq-assist\apps\ego-promptfolio
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Отредактируйте .env: SECRET_KEY, ADMIN_PASSWORD
python app.py
```

Откройте в браузере: [http://127.0.0.1:5000](http://127.0.0.1:5000)

Админ-панель: [http://127.0.0.1:5000/admin/login](http://127.0.0.1:5000/admin/login)

## Каждый следующий запуск

```powershell
Set-Location C:\Dev\oss\ego-faq-assist\apps\ego-promptfolio
.\.venv\Scripts\Activate.ps1
python app.py
```

Или без активации venv:

```powershell
.\.venv\Scripts\python app.py
```

Альтернатива:

```powershell
.\.venv\Scripts\flask --app app run --host=0.0.0.0 --port=5000
```

## Переменные окружения (`.env`)

| Переменная | Описание |
|------------|----------|
| `SECRET_KEY` | Секрет для сессий и CSRF (обязательно сменить в production) |
| `FLASK_DEBUG` | `1` — режим отладки; для production использовать `0` |
| `DATABASE_URL` | URI БД (по умолчанию SQLite в `instance/app.db`) |
| `ADMIN_USERNAME` | Логин администратора (по умолчанию `admin`) |
| `ADMIN_PASSWORD` | Обязательный пароль администратора; без него приложение не запустится |
| `FAQ_API_URL` | URL API FAQ-ассистента, например `https://ego-faq-assist.onrender.com/chat` |
| `LOG_LEVEL` | Уровень логов: `DEBUG`, `INFO`, … |

### Смена пароля администратора

1. Укажите новый `ADMIN_PASSWORD` в `.env`.
2. Перезапустите приложение — хеш пароля обновится для пользователя с `ADMIN_USERNAME`.

При запуске `ADMIN_PASSWORD` обязателен. Если переменная не задана или пуста, приложение завершит запуск с ошибкой. При каждом запуске пароль пользователя `ADMIN_USERNAME` обновляется значением из конфигурации.

## Развёртывание на Render

Для отдельного Web Service Ego Promptfolio используйте:

- **Root Directory:** `apps/ego-promptfolio`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
- **Health Check Path:** `/health`

Обязательные переменные окружения:

- `SECRET_KEY` — случайный секретный ключ.
- `ADMIN_USERNAME` — логин администратора.
- `ADMIN_PASSWORD` — надёжный пароль администратора.
- `FLASK_DEBUG=0` — отключённый режим отладки.
- `FAQ_API_URL=https://ego-faq-assist.onrender.com/chat` — API существующего FAQ-сервиса.

SQLite на временном диске бесплатного Render не обеспечивает постоянное хранение данных. Для долговременного хранения заявок потребуется подключить постоянное хранилище или PostgreSQL.

## Структура проекта

- `app.py` — точка входа
- `app_factory.py` — фабрика приложения и seed admin
- `templates/` — Jinja2-шаблоны
- `static/` — CSS, JS, изображения
- `instance/` — SQLite (создаётся автоматически, не в git)

## Функции

- Публичные страницы: главная, список кейсов, детальные страницы кейсов, форма обратной связи
- Админка: вход (Flask-Login), просмотр заявок, отметка «прочитано», удаление
- Flask-WTF + CSRF, валидация полей формы
- SQLAlchemy + SQLite

## Лицензия

MIT (при необходимости уточните для вашего репозитория).
