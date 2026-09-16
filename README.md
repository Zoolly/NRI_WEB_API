# NRI Projects API

Веб-сервис для работы с проектами NRI (PlanGraphicWeb): поиск, внесение
комментариев в поле «Дополнительная информация», прикрепление документов
(terrabyte), пакетная обработка и импорт списков из Excel.

## Запуск

```powershell
pip install -r requirements.txt
# заполнить .env (NRI_USER / NRI_PASSWORD)
start.bat            # или: python -m uvicorn app.main:app --port 8000
```

Интерфейс: http://127.0.0.1:8000 · Документация API: http://127.0.0.1:8000/docs

## Структура

```
app/
  main.py        # FastAPI: эндпоинты, Excel-импорт, пакетная обработка
  nri_client.py  # клиент NRI: вход, поиск, комментарии, документы
static/index.html  # веб-интерфейс (чёрно-жёлтая тема)
tools/diag_client.py  # диагностика: проверка входа и цепочек API
шаблон_комментариев.xlsx  # пример Excel-файла для импорта
```

## Как устроен клиент (важно для развития)

Вход повторяет браузер — именно этот порядок обязателен:

1. Портал `nrijs-web/rest` → POST `j_security_check`
   (кука `WASReqURL` приходит с пустым хостом `http:///...` — клиент
   подменяет её, иначе сервер падает с 500 NullPointerException)
2. `PlanGraphicWeb/plantc?form_type=1&id=<логин>` — пункт меню
   «Проекты строительства», инициализирует сессию PlanGraphicWeb
   (без него `projectsList.jsp` отдаёт 500 NPE)
3. Проверка: `projectsList.jsp` + парсинг `var userId = N` из HTML

Ключевые эндпоинты:

- **Поиск**: POST `/PlanGraphicWeb/ListProjects`
  (`applicationKey=key12`, `actionKey=prjbs.view`, `user=<логин>`,
  `searchBy`/`searchString`; поля: number, poscode (ЕРП), projectId, bsname...)
- **Комментарий** («Дополнительная информация», desc_proj):
  1. привязка проекта к сессии: GET `idbs/edit.do?projectId=...&man=<userId>`
     + GET `idbs/project/info.do?projectId=...` (без этого update уходит не туда)
  2. POST `idbs/project/update.do` c `index=10` (FIELD_ADDITIONAL_INFO)
  3. POST `CheckBProjectID` → POST `idbs/project/saveOrQuit.do`
     (`actionType=3` — «Сохранить», `edit=1`) — фиксация в БД
  4. для ретрансляторов (IType 5/6/10) корень `/idrep/project/` вместо `/idbs/`
- **Документы** (terrabyte): POST `/terrabyte/api/saveFile?catalogId=0&id=<pid>&type=prjbs&...`
  (тело — raw-байты файла; тип документа из `getDocTypes`;
  список — `getFilesInCatalog`)

Сессия сайта истекает — клиент перелогинивается автоматически (`_relogin`).

## Известные ограничения

- Обработка проектов строго последовательная (сервер держит «текущий
  проект» в сессии)
- Поле комментария — до 1024 символов (ограничение сайта)
- Часть эндпоинтов отдаёт нестрогий JSON (`{success:true}`) — есть
  терпимый парсер `_parse_json`
