def fetch_github_page(cursor: str | None = None) -> dict:
    return {"items": [], "next_cursor": cursor}


def sync_github_issues() -> list[dict]:
    page = fetch_github_page()
    return page["items"]
