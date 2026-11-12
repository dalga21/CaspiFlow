# Проверка опубликованной версии

12 ноября 2026, проверка реального публичного HTTPS-домена через HTTP-клиент и локально установленный Chromium/Playwright. Ответы приложения не подменялись mocks.

- Сайт: https://antibodies-victorian-give-explorer.trycloudflare.com
- Администратор: https://antibodies-victorian-give-explorer.trycloudflare.com/admin
- Health: https://antibodies-victorian-give-explorer.trycloudflare.com/api/health
- Исходный commit опубликованной сборки: `e7f8f750b38d`. Существующий код приложения сохранён. Более поздние commits добавляют публичные тесты, отчёт и ожидание внешней готовности в следующем запуске supervisor.

Адрес временный и зависит от работающего MacBook; текущий статус уточняется `backend/.venv/bin/python scripts/public_demo.py status` и внешним запросом health. После перезапуска Quick Tunnel адрес изменится.

## Фактические результаты

| Проверка | Результат |
|---|---|
| HTTPS `/`, `/api/health`, `/api/model`, `/api/dashboard`, `/api/forecast` | HTTP 200 |
| `/admin` без сессии | HTTP 307 → `/admin/login` |
| `/api/admin/data` без сессии / с подделанной cookie | HTTP 401 |
| POST admin login с чужим Origin | HTTP 403 |
| `.env`, `.runtime/.../secrets.json`, SQLite, `.git/config` | HTTP 404 |
| Неверные admin-пароли | 401 × 5, затем 429; удалены только записи попыток этого теста |
| Отдельный production build | PASS, Next.js Node runtime; npm ci по lockfile |
| TypeScript основного frontend и публичных тестов | PASS |
| Playwright по публичному HTTPS | **8 passed, 37.5 s**, 4 сценария × desktop/mobile Chromium |
| Модель по публичному API | Полное совпадение с `docs/ml_metrics.json`, версия `dd6d5aa09398` |
| Проверка секретов | Production/локальные секреты различны; значений нет в tracked files, production client JS и логах процессов |
| Приватные права файлов | Каталог 0700, пароль/секреты/production SQLite 0600 |

На самом первом запуске Cloudflare сначала вернул 530: домен был выдан до регистрации соединения. Первый набор получил 4 отказа desktop и 4 успеха mobile. После регистрации соединения весь набор повторён: 8/8 успешно. В скрипт добавлено ожидание **публичного** health перед объявлением следующего запуска готовым. Само получение URL больше не считается готовностью. Нет оснований обещать непрерывную доступность Quick Tunnel.

## Проверенные сценарии

1. Загрузка четырёх синтетических грузов, соответствие версии/метрик Random Forest, независимая арифметика CO₂ всех 12 сочетаний груз/маршрут. Загрузка реальных тайлов карты, масштабирование и popup порта. Ручной шторм 80% повышает прогноз задержки, сброс возвращает исходный сценарий.
2. Автопрогноз получает реальные данные Open-Meteo: HTTP 200, семь точек × 72 часа ветра и шесть морских × 72 часа волн. Для каждого из трёх графиков всех семи точек проверено соответствие наличия линии числовым данным API. На суше волны неприменимы. Прямой маршрут для всех грузов имеет ML-задержку, ETA и стоимость. Видна маркировка пространственного приближения морской ячейки.
3. Таможня: валидация неправильного ТН ВЭД в браузере, реальный POST через HTTPS → Next → FastAPI → отдельную SQLite, новая квитанция и SHA-256 после reload. Использовались только демонстрационные данные; удалялись только заявки с ID, созданными тестом и маркером `PUBLIC-DEMO-PLAYWRIGHT`. Рабочая локальная БД не затрагивалась.
4. Администратор: реальный вход новым production-паролем из приватного файла, серверная сессия, cookie Secure/HttpOnly/SameSite=Strict, чтение данных и запись тех же настроек через защищённый API. Выход отзывает доступ (401). Подделанная cookie и чужой Origin отклоняются. Тесты не сохраняют traces с содержимым авторизационных запросов.

Мобильная проверка — эмуляция iPhone 13 в Chromium, не физический iPhone/Safari. Публичный тест не является нагрузочным аудитом или проверкой доступности из всех сетей.

## Свидетельства

[HTTP-статусы и покрытие погоды](public_http_probe.json), [публичный браузер: HTTPS и сетевые запросы](public_browser_probe.json).

| Экран | Desktop | Mobile |
|---|---|---|
| Главная | [PNG](screenshots/public-home-desktop.png) | [PNG](screenshots/public-home-mobile.png) |
| Погодные графики | [PNG](screenshots/public-weather-desktop.png) | [PNG](screenshots/public-weather-mobile.png) |
| Таможенная квитанция | [PNG](screenshots/public-customs-desktop.png) | [PNG](screenshots/public-customs-mobile.png) |
| Админ-панель после входа | [PNG](screenshots/public-admin-desktop.png) | [PNG](screenshots/public-admin-mobile.png) |

Повтор из корня проекта:

```bash
CASPIFLOW_PUBLIC_URL=https://antibodies-victorian-give-explorer.trycloudflare.com \
  npm --prefix frontend run test:e2e -- --config playwright.public.config.ts
```

Сначала убедитесь, что адрес актуален и отвечает health. HTML-отчёт находится в `.runtime/public-playwright-report/index.html`. Набор читает отдельный production-пароль только из локального приватного файла и очищает свои демо-заявки только в `.runtime/public-demo/data/caspiflow.sqlite`, поэтому рассчитан на этот изолированный запуск, а не произвольный чужой сервер.

## Размещение и границы

Frontend, backend и постоянная SQLite размещены на диске/процессах этого MacBook; Cloudflare завершает публичный TLS и туннелирует только Next. Локальная версия остаётся на 3000/8000; опубликованная копия — на закрытых loopback-портах 3010/8010. Клиент обращается к одному HTTPS-origin, без запросов к localhost и без отдельного CORS.

Платные услуги не подключены. Согласно [ограничениям Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/), нет SLA, URL временный, предел 200 одновременных запросов, SSE не поддерживается. Нет sleep стороннего бесплатного backend-хостинга, но Mac должен оставаться включённым, с открытой крышкой и интернетом. `caffeinate` препятствует автоматическому сну при работающем supervisor; закрытие крышки и выключение не предотвращает. SQLite переживает перезапуск процессов на Mac; облачной реплики/бэкапа нет.

Для текущей ссылки ручных действий по авторизации в хостинге не требуется. Для независимой от Mac круглосуточной публикации потребуется авторизованный сервер/хостинг и постоянное хранилище. Такой перенос не выполнен и не заявляется.

Команды запуска, остановки, устройство секретов и ограничений — [PUBLIC_DEPLOYMENT.md](PUBLIC_DEPLOYMENT.md).
