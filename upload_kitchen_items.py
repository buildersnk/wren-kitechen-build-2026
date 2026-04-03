#!/usr/bin/env python3.13
"""
Read a TSV of action items, create issues in a repo, and add each issue to a Projects v2 project.

Usage:
  - pip3 install -r requirements.txt
  - Set GITHUB_TOKEN env var to your PAT.
  - Edit REPO_OWNER, REPO, PROJECT_OWNER, PROJECT_NUMBER, TSV_PATH below, then test connectivity:
      python3.13 upload_kitchen_items.py --test-connection
  - Run the upload:
      python3.13 upload_kitchen_items.py
"""

import argparse
import csv
import os
import sys
import time

import requests

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"

# === EDIT these settings ===
REPO_OWNER = "buildersnk"  # repo owner (user or org)
REPO = "wren-kitechen-build-2026"  # repo to create issues in
PROJECT_OWNER = "buildersnk"  # Projects v2 owner (user or org)
PROJECT_NUMBER = 2  # Projects v2 number from the owner page URL
TSV_PATH = "github_projects_kitchen_kanban.tsv"  # path to your TSV
# ============================

TOKEN = os.getenv("GITHUB_TOKEN")
if not TOKEN:
    print("Set GITHUB_TOKEN environment variable to a PAT with repo + project permissions.")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Verify token access to the configured GitHub repo and project without creating issues.",
    )
    return parser.parse_args()


def get_authenticated_user():
    resp = requests.get(f"{GITHUB_API}/user", headers=headers)
    resp.raise_for_status()
    return resp.json(), resp.headers


def get_repo(owner, repo):
    resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=headers)
    resp.raise_for_status()
    return resp.json()


def format_scope_hint(response_headers):
    oauth_scopes = response_headers.get("X-OAuth-Scopes")
    accepted_scopes = response_headers.get("X-Accepted-OAuth-Scopes")
    scope_lines = []
    if oauth_scopes is not None:
        scope_lines.append(f"token scopes: {oauth_scopes or '(none reported)'}")
    if accepted_scopes:
        scope_lines.append(f"accepted scopes: {accepted_scopes}")
    if not scope_lines:
        scope_lines.append(
            "for fine-grained PATs, make sure repository access includes Issues and Projects access is granted "
            "for the project owner; for classic PATs, include the `project` scope"
        )
    return " | ".join(scope_lines)

def get_project_node_id(owner, project_number):
    query = """
    query($login:String!, $number:Int!) {
      user(login:$login) {
        projectV2(number:$number) {
          id
          title
        }
      }
      organization(login:$login) {
        projectV2(number:$number) {
          id
          title
        }
      }
    }
    """
    vars = {"login": owner, "number": project_number}
    resp = requests.post(GITHUB_GRAPHQL, json={"query": query, "variables": vars}, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("errors", [])

    user_project = ((data.get("data") or {}).get("user") or {}).get("projectV2")
    org_project = ((data.get("data") or {}).get("organization") or {}).get("projectV2")
    proj = user_project or org_project
    if proj:
        print("Found project:", proj["title"], proj["id"])
        return proj["id"]

    forbidden_messages = [error["message"] for error in errors if error.get("type") == "FORBIDDEN"]
    not_found_messages = [error["message"] for error in errors if error.get("type") == "NOT_FOUND"]

    if forbidden_messages:
        raise RuntimeError(
            f"GitHub token cannot access Projects v2 for owner '{owner}'. "
            "The repo token works, but project access is forbidden. "
            "Use a token with project permissions and org authorization if this is an org project. "
            "For a classic PAT, include the `project` scope. "
            f"GitHub said: {'; '.join(forbidden_messages)}"
        )

    if not_found_messages:
        raise RuntimeError(
            f"Project owner '{owner}' could not be resolved or project #{project_number} does not exist there. "
            f"GitHub said: {'; '.join(not_found_messages)}"
        )

    if not proj:
        raise RuntimeError(
            f"Project v2 #{project_number} was not found for owner '{owner}'. "
            "Check that the project number is correct, the project belongs to this owner, "
            "and your token has project access."
        )


def test_connection():
    print("Testing GitHub token...")
    user, auth_headers = get_authenticated_user()
    print("Authenticated as:", user["login"])
    print("Auth details:", format_scope_hint(auth_headers))

    print(f"Checking repo access: {REPO_OWNER}/{REPO}")
    repo = get_repo(REPO_OWNER, REPO)
    print("Repo access OK:", repo["full_name"], f"(default branch: {repo['default_branch']})")

    print(f"Checking project access: owner {PROJECT_OWNER} / project #{PROJECT_NUMBER}")
    project_node_id = get_project_node_id(PROJECT_OWNER, PROJECT_NUMBER)
    print("Project access OK:", project_node_id)
    print("Connectivity test passed.")

def create_issue(owner, repo, title, body, assignees=None, labels=None):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
    payload = {"title": title, "body": body}
    if assignees:
        payload["assignees"] = assignees
    if labels:
        payload["labels"] = labels
    r = requests.post(url, json=payload, headers=headers)
    r.raise_for_status()
    return r.json()  # includes "node_id"

def add_issue_to_project(project_node_id, issue_node_id):
    mutation = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {projectId: $projectId, contentId: $contentId}) {
        item {
          id
        }
      }
    }
    """
    variables = {"projectId": project_node_id, "contentId": issue_node_id}
    r = requests.post(GITHUB_GRAPHQL, json={"query": mutation, "variables": variables}, headers=headers)
    r.raise_for_status()
    j = r.json()
    if "errors" in j:
        raise RuntimeError(j["errors"])
    return j

def read_tsv(path):
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter="\t")
        return list(reader)

def main():
    args = parse_args()
    if args.test_connection:
        test_connection()
        return

    rows = read_tsv(TSV_PATH)
    if not rows:
        print("No rows in TSV.")
        return

    proj_node_id = get_project_node_id(PROJECT_OWNER, PROJECT_NUMBER)

    for i, row in enumerate(rows, start=1):
        title = row.get("Title") or row.get("title") or f"Action item {i}"
        body_lines = []
        for k in row:
            if k.lower() in ("title",):
                continue
            body_lines.append(f"**{k}**: {row[k]}")
        body = "\n\n".join(body_lines)
        assignee = row.get("Assignee")
        labels = [l.strip() for l in row.get("Labels","").split(",")] if row.get("Labels") else None

        print(f"[{i}/{len(rows)}] Creating issue: {title}")
        issue = create_issue(REPO_OWNER, REPO, title, body, assignees=[assignee] if assignee else None, labels=labels)
        issue_node_id = issue.get("node_id")
        issue_url = issue.get("html_url")
        print("  Created:", issue_url, "node_id:", issue_node_id)

        print("  Adding issue to project...")
        add_issue_to_project(proj_node_id, issue_node_id)
        print("  Added to project.")
        time.sleep(0.5)  # courteous pacing to avoid rate limits

    print("Done.")

if __name__ == "__main__":
    main()
