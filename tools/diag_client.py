"""Диагностика: страница действия AddCommentAction (куда постит форма)."""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nri_client import NRIClient, AuthError, BASE_URL, OPERATOR_ID  # noqa: E402

OUT = Path(r"C:\Users\EMANGI~1\AppData\Local\Temp\opencode")


def save(name, text):
    (OUT / name).write_text(text, encoding="cp1251", errors="replace")
    print(f"  -> сохранено {name} ({len(text)} симв.)")


def main():
    username = input("Логин NRI: ").strip()
    password = getpass.getpass("Пароль NRI: ")
    pid = input("ID проекта (Enter = 566195): ").strip() or "566195"

    client = NRIClient(username, password)
    try:
        client.login()
        print("ВХОД ВЫПОЛНЕН УСПЕШНО")
    except AuthError as e:
        print(f"ОШИБКА ВХОДА: {e}")
        return

    items = client.search_projects(pid, "projectId", limit=1)
    if not items:
        print("Проект не найден")
        return
    proj = items[0]
    print(f"Проект: {proj['displayNumber']} wfProcessid={proj['wfProcessid']}")

    actions = client.list_actions(proj["id"], proj["wfProcessid"])
    allowed = [a for a in actions if a.get("isAllowed")]
    for a in allowed:
        print(f"  действие: {a['name']} url={a['url']} id={a['id']}")

    # Сохраняем страницы всех доступных действий
    for a in allowed:
        r = client._get(
            f"{BASE_URL}/{a['url']}",
            params={
                "processId": proj["wfProcessid"],
                "actionId": a["id"],
                "operatorId": OPERATOR_ID,
                "needproject": "true",
            },
            timeout=60,
        )
        print(f"\n[{r.status_code}] {a['url']}: {r.text[:150]}")
        save(f"action_{a['url']}.html", r.text)

    print("\nДиагностика завершена.")


if __name__ == "__main__":
    main()
