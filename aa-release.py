#!/usr/bin/env python3
"""Open a GitLab merge request that bumps the deploy-clowder ref."""

import os
import re
import subprocess  # nosec B404
import sys
from datetime import datetime
from urllib.parse import quote_plus

import requests

from binlib import summarize_openai

GITLAB_API_URL = os.getenv(
    "GITLAB_API_URL", "https://gitlab.cee.redhat.com/api/v4/commits"
)
GITLAB_REPO_URL = os.getenv(
    "GITLAB_REPO_URL",
    "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend",
)
DEPLOY_CLOWDER_FILE = "data/services/insights/tower-analytics/cicd/deploy-clowder.yml"


def get_last_commit_sha() -> str | None:
    """Return the commit SHA currently recorded in deploy-clowder.yml."""
    with open(DEPLOY_CLOWDER_FILE, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    for line in reversed(lines):
        if "ref:" in line:
            match = re.search(r"ref:\s+([a-f0-9]{40})", line)
            if match:
                return match.group(1)
    return None


def get_gitlab_commits(previous_sha: str) -> list:
    """Fetch commits on master that follow ``previous_sha``."""
    project_id = "automation-analytics/automation-analytics-backend"
    encoded_project_id = quote_plus(project_id)
    gitlab_host = GITLAB_API_URL.split("/api/")[0]
    url = (
        f"{gitlab_host}/api/v4/projects/{encoded_project_id}/repository/commits"
        f"?ref_name=master&since={previous_sha}"
    )
    headers = {"PRIVATE-TOKEN": os.getenv("GITLAB_API_TOKEN")}
    response = requests.get(url, headers=headers, verify=False, timeout=60)  # nosec B501 # nosemgrep
    if response.status_code == 200:
        return response.json()
    raise RuntimeError(f"Failed to get commits: {response.status_code}")


def generate_commit_summary(commits: list) -> str:
    """Summarize commit messages with OpenAI."""
    provider = summarize_openai(30)
    commit_text = "\n".join([commit["message"] for commit in commits])
    prompt = "Summarize the following commits in a few sentences:\n"
    return provider.improve_text(prompt, commit_text)


def update_deploy_clowder_file(new_sha: str) -> None:
    """Replace the ref line in deploy-clowder.yml with ``new_sha``."""
    with open(DEPLOY_CLOWDER_FILE, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
    with open(DEPLOY_CLOWDER_FILE, "w", encoding="utf-8") as handle:
        for line in lines:
            if "ref:" in line:
                handle.write(f"    ref: {new_sha}\n")
            else:
                handle.write(line)


def commit_and_push_changes() -> None:
    """Commit the deploy file and open the printed merge-request URL."""
    today = datetime.today().strftime("%Y-%m-%d")
    commit_message = f"AAP-AA-RELEASE-{today}"
    subprocess.run(["git", "add", DEPLOY_CLOWDER_FILE], check=False)  # nosec B603 B607
    subprocess.run(["git", "commit", "-m", commit_message], check=False)  # nosec B603 B607
    push_output = subprocess.check_output(  # nosec B603 B607
        ["git", "push", "-u", "origin", "master:" + commit_message],
        stderr=subprocess.STDOUT,
        text=True,
    )
    match = re.search(r"(https?://\S+/\S+/merge_requests/\d+)", push_output)
    if match:
        merge_request_url = match.group(1)
        print(f"Merge request URL: {merge_request_url}")
        subprocess.run(["xdg-open", merge_request_url], check=False)  # nosec B603 B607
        return
    print("No merge request URL found in push output.")
    sys.exit(1)


def main() -> None:
    """Bump deploy-clowder.yml to the latest commit and push a merge request."""
    last_sha = get_last_commit_sha()
    if not last_sha:
        print("No previous commit SHA found.")
        sys.exit(1)
    print(f"Last commit SHA: {last_sha}")
    commits = get_gitlab_commits(last_sha)
    if not commits:
        print("No commits found between previous SHA and HEAD.")
        sys.exit(1)
    print(f"Fetched {len(commits)} commits.")
    commit_summary = generate_commit_summary(commits)
    print(f"Commit Summary: {commit_summary}")
    latest_sha = commits[0]["id"]
    update_deploy_clowder_file(latest_sha)
    print(f"Updated deploy-clowder.yml with new SHA: {latest_sha}")
    commit_and_push_changes()
    print("Changes committed and pushed.")


if __name__ == "__main__":
    main()
