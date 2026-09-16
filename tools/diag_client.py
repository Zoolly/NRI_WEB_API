"""ТЕСТ 3: комментарий + сохранение в БД (saveOrQuit)."""

import getpass
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nri_client import NRIClient, AuthError, BASE_URL  # noqa: E402


def main():
    username = input("Логин NRI: ").strip()
    password = getpass.getpass("Пароль NRI: ")
    pid = input("ID проекта (Enter = 573364): ").strip() or "573364"

    client = NRIClient(username, password)
    try:
        client.login()
        print("ВХОД ВЫПОЛНЕН УСПЕШНО")
    except AuthError as e:
        print(f"ОШИБКА ВХОДА: {e}")
        return

    text = f"Тест API (saveOrQuit) {datetime.now().strftime('%H:%M:%S')}"
    print(f"Записываю комментарий: {text!r}")

    try:
        result = client.set_comment(int(pid), text)
        print(f"РЕЗУЛЬТАТ: {result}")
    except Exception as e:  # noqa: BLE001
        print(f"ОШИБКА: {e}")
        return

    # Контрольное чтение
    r = client._get(f"{BASE_URL}/idbs/project/info.do",
                    params={"projectId": pid})
    info = r.json().get("data", {})
    print(f"additionalInfo в info.do: {info.get('additionalInfo')!r}")
    print("\nТеперь проверьте на САЙТЕ (обновите карточку проекта) — "
          "значение должно совпасть.")


if __name__ == "__main__":
    main()
