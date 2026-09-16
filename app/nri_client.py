"""Клиент NRI (PlanGraphicWeb + портал + terrabyte).

Цепочка как в браузере:
  1. вход через портал nrijs-web (j_security_check)
  2. пункт меню «Проекты строительства» (plantc) — инициализация PlanGraphicWeb
  3. поиск проектов — POST ListProjects
  4. комментарий («Дополнительная информация») — idbs/project/update.do (index=10)
  5. документы — terrabyte /api/saveFile
"""

import re
from urllib.parse import urljoin

import requests

HOST = "http://nri-application.vimpelcom.ru"
BASE_URL = f"{HOST}/PlanGraphicWeb"
PORTAL_URL = f"{HOST}/nrijs-web/rest"
NRIJS_URL = f"{HOST}/nrijs-web"
PLANTC_URL = f"{BASE_URL}/plantc"
PROJECTS_URL = f"{BASE_URL}/projectsList.jsp"
TERRABYTE_API = f"{HOST}/terrabyte/api"

FIELD_ADDITIONAL_INFO = 10  # поле «Дополнительная информация» (desc_proj)
REPEATER_ITYPES = (5, 6, 10)
OPERATOR_ID = "11977"  # оператор портала (как на странице проектов)


class AuthError(RuntimeError):
    pass


class NotFoundError(RuntimeError):
    pass


class NRIClient:
    SEARCH_FIELDS = {
        "all": "-1",
        "number": "number",       # по номеру ДЗ
        "project_id": "projectId",
        "bsname": "bsname",       # по наименованию БС
        "posname": "posname",     # по наименованию площадки
        "gfk": "gfk",
        "poscode": "poscode",   # по номеру позиции (ЕРП)
        "poNumber": "poNumber",
        "status": "status",
        "owner": "owner",
    }

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.user_id = "0"
        self._bound_pid = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "ru,en;q=0.8",
        })

    # ---------- низкий уровень ----------

    def _fix_encoding(self, r: requests.Response):
        if not r.encoding or r.encoding.lower() in ("iso-8859-1", "ascii"):
            r.encoding = "cp1251"

    def _get(self, url: str, timeout: int = 60, _retried: bool = False, **kw) -> requests.Response:
        r = self.session.get(url, timeout=timeout, **kw)
        self._fix_encoding(r)
        # Сессия истекла — перелогин и повтор запроса
        if not _retried and (self._is_login_page(r) or "Invalid username" in r.text):
            self._relogin()
            return self._get(url, timeout=timeout, _retried=True, **kw)
        return r

    def _post(self, url: str, timeout: int = 120, _retried: bool = False, **kw) -> requests.Response:
        r = self.session.post(url, timeout=timeout, **kw)
        self._fix_encoding(r)
        if not _retried and (self._is_login_page(r) or "Invalid username" in r.text):
            self._relogin()
            return self._post(url, timeout=timeout, _retried=True, **kw)
        return r

    def _relogin(self):
        self.session.cookies.clear()
        self._bound_pid = None
        self.login()

    @staticmethod
    def _is_login_page(r: requests.Response) -> bool:
        return "j_security_check" in r.url or "j_username" in r.text

    @staticmethod
    def _parse_json(text: str):
        """Терпимый парсер: часть эндпоинтов отдаёт нестрогий JSON ({success:true})."""
        import ast
        try:
            return __import__("json").loads(text)
        except ValueError:
            pass
        try:
            fixed = re.sub(r'([{,]\s*)([A-Za-z_]\w*)\s*:', r'\1"\2":', text)
            fixed = (fixed.replace(":true", ":True").replace(":false", ":False")
                     .replace(":null", ":None")
                     .replace("[true", "[True").replace("[false", "[False")
                     .replace("[null", "[None")
                     .replace(",true", ",True").replace(",false", ",False")
                     .replace(",null", ",None"))
            return ast.literal_eval(fixed)
        except (ValueError, SyntaxError):
            return None

    def _check_response(self, r: requests.Response, what: str) -> dict:
        if r.status_code >= 500:
            raise RuntimeError(f"{what}: сервер вернул ошибку {r.status_code}: "
                               f"{r.text[:200]}")
        payload = self._parse_json(r.text)
        if payload is None:
            raise RuntimeError(f"{what}: не-JSON ответ: {r.text[:200]}")
        if isinstance(payload, dict) and payload.get("success") is False:
            msg = payload.get("error") or payload.get("message") or str(payload)[:300]
            raise RuntimeError(f"{what}: {msg}")
        return payload

    # ---------- авторизация ----------

    def login(self):
        # Используются прямые вызовы session (минуя _get/_post с
        # авто-перелогином), иначе получится бесконечная рекурсия.
        # 1. Страница логина портала
        r = self.session.get(f"{PORTAL_URL}/", timeout=60)
        self._fix_encoding(r)
        # WebSphere отдаёт куку WASReqURL с пустым хостом ("http:///..."),
        # из-за которой после логина сервер падает с 500 NPE — исправляем.
        for c in self.session.cookies:
            if c.name == "WASReqURL":
                c.value = f"{PORTAL_URL}/"
        # 2. Логин на портале
        r = self.session.post(
            f"{PORTAL_URL}/j_security_check",
            data={"j_username": self.username, "j_password": self.password},
            timeout=60,
        )
        self._fix_encoding(r)
        if self._is_login_page(r) or "Invalid username" in r.text:
            raise AuthError("Не удалось войти: неверный логин/пароль")
        # 3. Пункт меню «Проекты строительства» — инициализация PlanGraphicWeb
        #    (без него projectsList.jsp падает с NullPointerException)
        r = self.session.get(f"{PLANTC_URL}?form_type=1&id={self.username}",
                             timeout=120)
        self._fix_encoding(r)
        # 4. Проверка доступности списка проектов + userId
        check = self.session.get(PROJECTS_URL, timeout=60)
        self._fix_encoding(check)
        if self._is_login_page(check):
            raise AuthError("Сессия PlanGraphicWeb не создана после входа через портал")
        if check.status_code >= 500 or "NullPointerException" in check.text:
            raise AuthError("PlanGraphicWeb вернул ошибку после инициализации (plantc)")
        m = re.search(r"var\s+userId\s*=\s*(\d+)", check.text)
        self.user_id = m.group(1) if m else "0"
        return {"ok": True, "userId": self.user_id}

    # ---------- поиск ----------

    def search_projects(self, query: str | None = None,
                        search_by: str = "-1", start: int = 0,
                        limit: int = 200, region_id=None,
                        subsidiary_id=None) -> list:
        data = {
            "applicationKey": "key12",
            "actionKey": "prjbs.view",
            "user": self.username,
            "searchBy": self.SEARCH_FIELDS.get(search_by, search_by),
            "start": start,
            "limit": limit,
        }
        if query is not None:
            data["searchString"] = query
        if region_id:
            data["regionId"] = region_id
        if subsidiary_id:
            data["subsidiaryId"] = subsidiary_id
        r = self._post(f"{BASE_URL}/ListProjects", data=data)
        return self._check_response(r, "Поиск проектов").get("items", [])

    # ---------- справочники (регионы / филиалы) ----------

    def _lookup_params(self):
        return {
            "applicationKey": "key12",
            "actionKey": "prjbs.view",
            "user": self.username,
        }

    def list_regions(self) -> list:
        r = self._post(f"{NRIJS_URL}/ListRegions", data=self._lookup_params())
        return self._check_response(r, "Список регионов").get("items", [])

    def list_subsidiaries(self, region_id=None) -> list:
        data = self._lookup_params()
        if region_id:
            data["regionId"] = region_id
        r = self._post(f"{NRIJS_URL}/ListSubsidiaries", data=data)
        return self._check_response(r, "Список филиалов").get("items", [])

    # ---------- карточка проекта ----------

    def _rest_root(self, itype: int | None) -> str:
        if itype in REPEATER_ITYPES:
            return f"{BASE_URL}/idrep/project"
        return f"{BASE_URL}/idbs/project"

    def _bind_project(self, pid: int):
        """Привязка проекта к сессии (как открытие карточки в браузере):
        edit.do + info.do — без этого update.do меняет не тот проект."""
        if self._bound_pid == pid:
            return
        self._get(
            f"{BASE_URL}/idbs/edit.do",
            params={"projectId": pid, "man": self.user_id,
                    "formopener": "new", "mode": 1, "type": 1},
            timeout=120,
        )
        r = self._get(f"{BASE_URL}/idbs/project/info.do",
                      params={"projectId": pid})
        self._check_response(r, "Открытие карточки проекта")
        self._bound_pid = pid

    def get_project_info(self, pid: int) -> dict:
        self._bind_project(pid)
        r = self._get(f"{BASE_URL}/idbs/project/info.do",
                      params={"projectId": pid})
        return self._check_response(r, "Данные проекта").get("data", {})

    # ---------- комментарий («Дополнительная информация») ----------

    def set_comment(self, pid: int, text: str, itype: int | None = None) -> dict:
        """Записать текст в поле «Дополнительная информация» (desc_proj)
        и зафиксировать в БД (как кнопка «Сохранить» в браузере):
        update.do -> CheckBProjectID -> saveOrQuit.do."""
        self._bind_project(pid)
        # 1. Изменение поля (в сессии)
        r = self._post(
            f"{self._rest_root(itype)}/update.do",
            data={
                "index": FIELD_ADDITIONAL_INFO,
                "value": text,
                "noRedirect": 1,
                "context": "/PlanGraphicWeb",
            },
        )
        self._check_response(r, "Изменение комментария")
        # 2. Проверка (как в браузере перед сохранением)
        r = self._post(
            f"{BASE_URL}/CheckBProjectID",
            data={"noRedirect": 1, "context": "/PlanGraphicWeb"},
        )
        self._check_response(r, "Проверка проекта")
        # 3. Сохранение в БД: actionType=3 (Сохранить), edit=1 (правка)
        r = self._post(
            f"{self._rest_root(itype)}/saveOrQuit.do",
            data={"actionType": 3, "edit": 1,
                  "noRedirect": 1, "context": "/PlanGraphicWeb"},
        )
        return self._check_response(r, "Сохранение проекта")

    # ---------- доступные действия (workflow) ----------

    def list_actions(self, pid: int, process_id, operator_id: str = OPERATOR_ID) -> list:
        """Список доступных действий проекта (панель «Доступные действия»)."""
        r = self._post(
            f"{BASE_URL}/ListAvailableActions",
            data={
                "operatorId": operator_id,
                "processId": process_id,
                "isHidden": "N",
                "projectId": pid,
            },
        )
        return self._check_response(r, "Список доступных действий").get("items", [])

    def run_action(self, pid: int, process_id, action_url: str, action_id,
                   comment: str = "") -> dict:
        """Выполнить действие workflow без диалога (как кнопка в диалоге сайта):
        проверка сообщений -> POST на URL действия с force=true."""
        # 1. Сообщения перед выполнением (ListActionResultMessages)
        r = self._post(
            f"{BASE_URL}/ListActionResultMessages",
            data={"processId": process_id, "projectId": pid},
        )
        try:
            msgs = self._check_response(r, "Проверка перед действием").get("items", [])
        except RuntimeError:
            msgs = []
        errors = [m.get("msg", "") for m in msgs if m.get("msgtype") == 0]
        if errors:
            raise RuntimeError("Действие заблокировано: " + "; ".join(
                e for e in errors if e))
        # 2. Выполнение (force=true подтверждает предупреждения,
        #    как кнопка Yes в диалоге сайта)
        r = self._post(
            f"{BASE_URL}/{action_url}",
            data={
                "processId": process_id,
                "actionId": action_id,
                "force": "true",
                "doCheckFormProjectId": "true",
                "comment": comment,
                "reloadPage": "false",
                "needproject": "true",
            },
            timeout=300,
        )
        payload = self._parse_json(r.text)
        if payload is None:
            if r.status_code == 200 and not r.text.strip():
                return {"success": True}
            raise RuntimeError(f"Не-JSON ответ: {r.text[:200]}")
        if payload.get("success") is False:
            raise RuntimeError(payload.get("message")
                               or str(payload.get("messages"))[:300] or "Действие не выполнено")
        return payload

    # ---------- документы (terrabyte) ----------

    def get_doc_types(self, pid: int) -> list:
        r = self._post(
            f"{TERRABYTE_API}/getDocTypes",
            data={"id": pid, "type": "prjbs", "updateAcl": "true"},
        )
        return self._check_response(r, "Типы документов").get("items", [])

    def list_files(self, pid: int, catalog_id: int = 0) -> list:
        r = self._post(
            f"{TERRABYTE_API}/getFilesInCatalog",
            data={
                "id": pid, "type": "prjbs", "catalogId": catalog_id,
                "fileNameMask": "", "docTypeId": "", "includeSubDirs": "true",
            },
        )
        return self._check_response(r, "Список файлов").get("items", [])

    def attach_file(self, pid: int, filename: str, content: bytes,
                    doc_type_id, description: str = "") -> dict:
        """Прикрепить документ к проекту (terrabyte saveFile)."""
        from urllib.parse import quote
        qs = (
            f"catalogId=0&id={pid}&type=prjbs"
            f"&fileName={quote(filename)}"
            f"&substantiation=false&documentType={doc_type_id}"
            f"&description={quote(description)}"
            f"&reference=null&file=true&fileId=null"
            f"&registeredAt=&intPhotograph=&extPhotograph="
        )
        r = self._post(
            f"{TERRABYTE_API}/saveFile?{qs}",
            data=content,
            headers={"Content-Type": "application/octet-stream"},
            timeout=300,
        )
        return self._check_response(r, "Загрузка документа")

    def download_file(self, pid: int, file_id, version=None) -> bytes:
        params = {"fileId": file_id, "id": pid, "type": "prjbs"}
        if version:
            params["version"] = version
        r = self._post(f"{TERRABYTE_API}/downloadFile", params=params,
                       timeout=300)
        if r.status_code != 200:
            raise RuntimeError(f"Скачивание файла: ошибка {r.status_code}")
        return r.content
