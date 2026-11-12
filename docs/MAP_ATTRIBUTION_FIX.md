# Атрибуция интерактивной карты

13 ноября 2026. Значок оказался встроенным SVG-флагом Leaflet **1.9.4**: `ukrainianFlag`, класс `leaflet-attribution-flag`, добавляемый в стандартный `Control.Attribution.options.prefix`. Точный источник установлен в `frontend/node_modules/leaflet/dist/leaflet-src.js`, строки 5743 и 5762. Это не тайл OpenStreetMap, не CSS проекта и не внешний виджет.

Использован штатный `AttributionControl` React Leaflet с текстовым prefix «Leaflet». Автоматическое создание стандартного control отключено в `MapContainer`, вместо него отображается один явно созданный control с теми же атрибуциями слоя. Никакие элементы не скрываются CSS и библиотека в node_modules не патчится.

Сохранились ссылки:

- [Leaflet](https://leafletjs.com) — библиотека карты.
- © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors — авторы картографических данных; используются прежние тайлы самого OpenStreetMap.

[Лицензия Leaflet 1.9.4 (BSD-2-Clause)](https://github.com/Leaflet/Leaflet/blob/v1.9.4/LICENSE) требует сохранения уведомлений об авторских правах и условий при распространении, но не показа флага. Лицензия/уведомления пакета не изменены. [Штатная опция prefix](https://leafletjs.com/reference-1.9.4.html#control-attribution-prefix) допускает настройку префикса. Видимая атрибуция данных сохранена согласно [правилам OSM](https://operations.osmfoundation.org/policies/tiles/).

Тайловый URL, координаты/центр, диапазон масштаба, маршруты, маркеры, popup, геометрия и обработчики взаимодействия не менялись. Компонент общий для ручного и автоматического режимов.

Проверка: production build, TypeScript; Playwright desktop/mobile для маркеров, всех семи popup, масштаба, перемещения, смены маршрута, работы без внешних тайлов и автоматического режима. В тест карты добавлены проверки единственного видимого блока атрибуции, обеих точных ссылок и отсутствия SVG/изображений флага. Скриншоты: [desktop](screenshots/map-attribution-desktop.png), [mobile](screenshots/map-attribution-mobile.png).
