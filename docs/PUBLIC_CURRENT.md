# Текущая публичная версия CaspiFlow

13 ноября 2026. Восстановлена публикация релиза `a887c0542195` (функциональность приложения сохранена) без отдельного режима «Демо для жюри».

- Сайт: https://evolution-pace-dana-butterfly.trycloudflare.com
- Админ-панель: https://evolution-pace-dana-butterfly.trycloudflare.com/admin
- Health: https://evolution-pace-dana-butterfly.trycloudflare.com/api/health

Это актуальный адрес после переключения релиза. Предыдущие ссылки Quick Tunnel больше не используются. База, существующие грузы/заявки/настройки и пароль администратора сохранены. Перед переключением сделана приватная SQLite backup; локальная рабочая база не копировалась в публичную.

## Что опубликовано

Карточка «Что делать логисту?», ручная симуляция шторма, Open-Meteo, графики, корректировка нулевой волны для сухопутного пути и явное ограничение его ML-оценки. Кнопка «Сформировать отчёт» скачивает PDF показанного расчёта в ручном и автоматическом режимах. Отдельная кнопка и пошаговая панель «Демо для жюри» удалены.

## Реальная проверка HTTPS

Полный публичный Playwright: **8/8 passed**, desktop/mobile Chromium. Проверены health/метрики RF, грузы, независимая арифметика CO₂, карта и атрибуция, шторм/сброс, все семь погодных точек, графики, настоящая запись и чтение тестовой таможенной заявки, admin login/logout, Secure/HttpOnly/SameSite cookie, отказ без сессии и чужой Origin.

Дополнительная проверка новой версии в обоих размерах: отсутствие удалённого режима, карточка решения, сухопутный wave=0 и validation_scope=unvalidated_land, условность рекомендации. Через публичный браузер скачаны **четыре PDF**: manual/auto × desktop/mobile. Проверены заголовок PDF, кириллица/содержимое выбранного груза, режим шторма 100%, источники и отсутствие production-секретов. Ошибок JS и горизонтального переполнения не обнаружено. Мобильная проверка — Chromium-эмуляция, не физический Safari.

Фактические HTTP: `/` и `/api/health` — 200; `/api/admin/data` без сессии — 401; `.env`, `.runtime/.../secrets.json`, SQLite — 404. Production JS и скачанные PDF проверены на отсутствие значений секретов. После удаления только тестовых заявок содержимое таблиц shipments/customs/settings совпало с состоянием до публикации, файлы доступа не менялись.

Свидетельства: [public_current_probe.json](public_current_probe.json), [desktop](screenshots/public-current-desktop.png), [mobile](screenshots/public-current-mobile.png). Результаты предыдущих публикаций в других отчётах относятся к их историческим URL.

## Где работает и как перезапустить

Next.js и FastAPI работают на MacBook в отдельном release-каталоге `.runtime/public-demo/releases/a887c054219581210cd32f1c5755d917a8e4dfc3`. SQLite находится на постоянном диске MacBook: `.runtime/public-demo/data/caspiflow.sqlite`. Cloudflare Tunnel предоставляет единый HTTPS-origin; FastAPI напрямую наружу не опубликован.

MacBook должен оставаться включённым, с открытой крышкой и интернетом. Туннель временный, без SLA; после остановки/нового запуска адрес изменится. Данные SQLite сохраняются между запусками, облачной реплики нет. Платные услуги не подключались.

```bash
backend/.venv/bin/python scripts/public_demo.py status
# Остановить публикацию:
backend/.venv/bin/python scripts/public_demo.py stop
# Собрать текущий Git HEAD и запустить снова с НОВЫМ URL:
backend/.venv/bin/python scripts/public_demo.py start
```

При следующем запуске брать адрес из status, не из старого чата. Пароль хранится только в приватном локальном `.runtime/public-demo/admin-password.txt`; в отчёт/GitHub он не включается.

## Восстановление временного туннеля

Старый адрес перестал разрешаться в DNS; cloudflared сообщал `Unauthorized: Tunnel not found`, хотя локальный health оставался 200. Публикация пересоздана с новым адресом, база и пароль сохранены. Это потеря временного туннеля, не подтверждённая ошибка Next.js/FastAPI. Проверка — [TUNNEL_RECOVERY.json](TUNNEL_RECOVERY.json).

Команда `status` теперь проверяет внешний HTTPS health, а не только существование PID. Четыре регрессии проверяют здоровый JSON, HTTP 530, неверный health-ответ и DNS/connection error. Если supervisor running, но Public HTTPS unavailable, выполнить stop и start; получить НОВЫЙ адрес из status. Временные туннели не имеют гарантии доступности.
