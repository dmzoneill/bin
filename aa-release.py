#!/usr/bin/env python3

import os
import sys
import subprocess
import requests
import re
import urllib
from datetime import datetime

# Define your API and repository URLs
GITLAB_API_URL = "https://gitlab.cee.redhat.com/api/v4/commits"
GITLAB_REPO_URL = "https://gitlab.cee.redhat.com/automation-analytics/automation-analytics-backend"
DEPLOY_CLOWDER_FILE = "data/services/insights/tower-analytics/cicd/deploy-clowder.yml"

class OpenAIProvider:
    def __init__(self):
        self.api_key = os.getenv("AI_API_KEY")
        if not self.api_key:
            raise EnvironmentError("AI_API_KEY not set in environment.")
        self.endpoint = "https://api.openai.com/v1/chat/completions"
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def improve_text(self, prompt: str, text: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.3,
        }

        response = requests.post(self.endpoint, json=body, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()

        raise Exception(
            f"OpenAI API call failed: {response.status_code} - {response.text}"
        )

# --- Function to Extract Last Commit SHA from deploy-clowder.yml ---
def get_last_commit_sha():
    with open(DEPLOY_CLOWDER_FILE, 'r') as file:
        lines = file.readlines()
    
    for line in reversed(lines):
        if "ref:" in line:
            # Extract the SHA1 commit id
            match = re.search(r"ref:\s+([a-f0-9]{40})", line)
            if match:
                return match.group(1)
    return None

# --- Function to Get GitLab Commits ---
def get_gitlab_commits(previous_sha):
    # GitLab project ID or URL-encoded namespace/project name
    project_id = "automation-analytics/automation-analytics-backend"
    
    # URL encode the project ID to ensure it's properly formatted for the API
    encoded_project_id = urllib.parse.quote_plus(project_id)

    # Create the URL for fetching commits with the correct repository path
    url = f"https://gitlab.cee.redhat.com/api/v4/projects/{encoded_project_id}/repository/commits?ref_name=master&since={previous_sha}"

    headers = {
        "PRIVATE-TOKEN": os.getenv("GITLAB_API_TOKEN")
    }

    # Disable SSL verification by setting verify=False
    response = requests.get(url, headers=headers, verify=False)

    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed to get commits: {response.status_code}")

# --- Function to Generate Commit Summary ---
def generate_commit_summary(commits):
    openai = OpenAIProvider()
    commit_text = "\n".join([commit["message"] for commit in commits])
    prompt = "Summarize the following commits in a few sentences:\n"
    summary = openai.improve_text(prompt, commit_text)
    return summary

# --- Function to Update deploy-clowder.yml with Latest Commit SHA ---
def update_deploy_clowder_file(new_sha):
    with open(DEPLOY_CLOWDER_FILE, 'r') as file:
        lines = file.readlines()

    with open(DEPLOY_CLOWDER_FILE, 'w') as file:
        for line in lines:
            if "ref:" in line:
                file.write(f"    ref: {new_sha}\n")
            else:
                file.write(line)

# --- Function to Commit and Push Changes ---
def commit_and_push_changes():
    # Get today's date for commit message
    today = datetime.today().strftime('%Y-%m-%d')
    commit_message = f"AAP-AA-RELEASE-{today}"

    # Commit and push the file
    subprocess.run(["git", "add", DEPLOY_CLOWDER_FILE])
    subprocess.run(["git", "commit", "-m", commit_message])

    # Push the changes and capture the output
    push_output = subprocess.check_output(["git", "push", "-u", "origin", "master:" + commit_message], stderr=subprocess.STDOUT, text=True)

    # Extract the URL for the pull request/merge request from the push output
    match = re.search(r"(https?://\S+/\S+/merge_requests/\d+)", push_output)
    if match:
        merge_request_url = match.group(1)
        print(f"Merge request URL: {merge_request_url}")
        
        # Open the merge request URL using xdg-open
        subprocess.run(["xdg-open", merge_request_url])
    else:
        print("No merge request URL found in push output.")
        sys.exit(1)

# --- Main Function ---
def main():
    # Step 1: Get last commit SHA from deploy-clowder.yml
    last_sha = get_last_commit_sha()
    if not last_sha:
        print("No previous commit SHA found.")
        sys.exit(1)

    print(f"Last commit SHA: {last_sha}")

    # Step 2: Get commits from GitLab from previous SHA to HEAD
    commits = get_gitlab_commits(last_sha)
    if not commits:
        print("No commits found between previous SHA and HEAD.")
        sys.exit(1)

    print(f"Fetched {len(commits)} commits.")

    # Step 3: Generate summary of commits
    commit_summary = generate_commit_summary(commits)
    print(f"Commit Summary: {commit_summary}")

    # Step 4: Update deploy-clowder.yml with the latest commit SHA
    latest_sha = commits[0]["id"]
    update_deploy_clowder_file(latest_sha)
    print(f"Updated deploy-clowder.yml with new SHA: {latest_sha}")

    # Step 5: Commit and push the changes
    commit_and_push_changes()
    print("Changes committed and pushed.")

if __name__ == "__main__":
    main()
