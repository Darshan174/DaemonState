from app.github_sync import sync_github_issues


def test_sync_github_issues_returns_items():
    assert sync_github_issues() == []
