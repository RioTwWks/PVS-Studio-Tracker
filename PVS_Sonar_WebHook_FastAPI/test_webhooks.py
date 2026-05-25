"""
Скрипт для тестов webhook endpoints.

Использование:
    python test_webhooks.py [--base-url URL] [--type tfs|sonarqube]

Примеры использования:
    python test_webhooks.py --base-url http://localhost:8080 --type tfs
    python test_webhooks.py --base-url http://qube:8080 --type sonarqube
"""

import argparse
import hashlib
import hmac
import json
import sys
from datetime import datetime
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth


# Тест TFVC/Git webhook endpoint
def test_tfs_git_webhook(base_url: str, username: str, password: str, project_name: str = "TestProject", group_name: str = "TestGroup"):
    # Имитирует событие Git push из TFS
    url = f"{base_url}/webhook"

    # Пример Git push payload (TFS формат)
    payload = {
        "eventType": "git.push",
        "resource": {
            "commits": [
                {
                    "commitId": "abc123def456",
                    "author": {
                        "name": "Test User",
                        "email": "test@example.com",
                        "date": datetime.now().isoformat()
                    },
                    "comment": "Test commit for webhook testing",
                    "changes": [
                        {
                            "changeType": "edit",
                            "item": {
                                "path": "/src/main.cpp",
                                "gitObjectType": "blob"
                            }
                        },
                        {
                            "changeType": "add",
                            "item": {
                                "path": "/src/utils.h",
                                "gitObjectType": "blob"
                            }
                        }
                    ]
                }
            ],
            "refUpdates": [
                {
                    "name": "refs/heads/master",
                    "oldObjectId": "0000000000000000000000000000000000000000",
                    "newObjectId": "abc123def456"
                }
            ],
            "repository": {
                "id": "repo-123",
                "name": f"{project_name}",
                "url": "http://qtfs:8080/tfs/QUIK/TestRepo/_git/TestRepo",
                "project": {
                    "name": group_name,
                    "id": "proj-456"
                }
            },
            "pushedBy": {
                "displayName": "Test User",
                "id": "user-789"
            },
            "pushId": 12345,
            "date": datetime.now().isoformat()
        },
        "resourceVersion": 2.0,
        "resourceContainers": {}
    }

    # Headers
    headers = {
        "Content-Type": "application/json",
        "X-TFS-Repo-Type": "Git",
        "X-TFS-Repo-Name": f"{project_name}/master",
        "X-TFS-Proj-Name": project_name,
        "X-TFS-Group-Name": group_name
    }

    print(f"\n{'='*60}")
    print("Testing TFS/Git Webhook")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)[:500]}...")
    print(f"Headers: {headers}")
    print(f"Auth: {username}:***")

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            auth=HTTPBasicAuth(username, password),
            verify=False  # Disable SSL verification for testing
        )

        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body: {response.text[:500]}")

        if response.status_code == 200:
            print("✓ TFS/Git webhook test PASSED")
            return True
        else:
            print(f"✗ TFS/Git webhook test FAILED (status: {response.status_code})")
            return False

    except requests.exceptions.ConnectionError as e:
        print(f"✗ Connection error: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


# Тест TFVC webhook endpoint
def test_tfvc_webhook(base_url: str, username: str, password: str, project_name: str = "TestProject", group_name: str = "TestGroup"):
    # Имитирует событие TFVC check-in
    url = f"{base_url}/webhook"

    # Пример TFVC check-in payload
    payload = {
        "eventType": "tfvc.checkin",
        "resource": {
            "changesetId": 98765,
            "author": {
                "displayName": "Test User",
                "id": "user-789"
            },
            "comment": "Test check-in for webhook testing",
            "createdDate": datetime.now().isoformat(),
            "changes": [
                {
                    "changeType": "edit",
                    "item": {
                        "path": "$/TestProject/src/main.cpp"
                    }
                },
                {
                    "changeType": "add",
                    "item": {
                        "path": "$/TestProject/src/utils.cpp"
                    }
                }
            ],
            "workItems": []
        },
        "resourceVersion": 2.0
    }

    # Headers
    headers = {
        "Content-Type": "application/json",
        "X-TFS-Repo-Type": "TFVC",
        "X-TFS-Repo-Name": f"{project_name}/master",
        "X-TFS-Proj-Name": project_name,
        "X-TFS-Group-Name": group_name
    }

    print(f"\n{'='*60}")
    print("Testing TFVC Webhook")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2)[:500]}...")
    print(f"Headers: {headers}")

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            auth=HTTPBasicAuth(username, password),
            verify=False
        )

        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body: {response.text[:500]}")

        if response.status_code == 200:
            print("✓ TFVC webhook test PASSED")
            return True
        else:
            print(f"✗ TFVC webhook test FAILED (status: {response.status_code})")
            return False

    except requests.exceptions.ConnectionError as e:
        print(f"✗ Connection error: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


# Тест SonarQube webhook endpoint
def test_sonarqube_webhook(
    base_url: str, 
    project_key: str = "test-project", 
    project_name: str = "Test Project",
    secret: Optional[str] = None,
    verify_signature: bool = False
):
    # Имитирует событие quality gate из SonarQube
    url = f"{base_url}/sonarqube-webhook"

    # Пример SonarQube webhook payload
    payload = {
        "serverUrl": "http://qube",
        "taskId": "AXYZ123456789",
        "status": "SUCCESS",
        "analysedAt": datetime.now().isoformat(),
        "revision": "abc123",
        "project": {
            "key": project_key,
            "name": project_name,
            "url": f"http://qube/dashboard?id={project_key}"
        },
        "branch": {
            "name": "master",
            "type": "BRANCH",
            "isMain": True,
            "url": f"http://qube/dashboard?id={project_key}&branch=master"
        },
        "qualityGate": {
            "name": "Default Quality Gate",
            "status": "OK",
            "conditions": [
                {
                    "metric": "new_coverage",
                    "operator": "LT",
                    "value": "85.5",
                    "status": "OK",
                    "errorThreshold": "80"
                },
                {
                    "metric": "new_reliability_rating",
                    "operator": "GT",
                    "value": "1",
                    "status": "OK",
                    "errorThreshold": "1"
                }
            ]
        },
        "properties": {
            "sonar.projectKey": project_key,
            "sonar.projectName": project_name
        }
    }

    # Headers
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SonarQube/10.0"
    }

    # Добавляет подпись, если указан секрет
    if secret and verify_signature:
        body_bytes = json.dumps(payload).encode('utf-8')
        signature = hmac.new(
            key=secret.encode('utf-8'),
            msg=body_bytes,
            digestmod=hashlib.sha256
        ).hexdigest()
        headers["X-Sonar-Webhook-HMAC-SHA256"] = signature
        print(f"Signature: {signature[:50]}...")

    print(f"\n{'='*60}")
    print("Testing SonarQube Webhook")
    print(f"{'='*60}")
    print(f"URL: {url}")
    print(f"Project: {project_name} ({project_key})")
    print(f"Payload: {json.dumps(payload, indent=2)[:500]}...")
    print(f"Headers: {headers}")

    try:
        response = requests.post(
            url,
            json=payload,
            headers=headers,
            verify=False
        )

        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body: {response.text[:500]}")

        if response.status_code == 200:
            print("✓ SonarQube webhook test PASSED")
            return True
        else:
            print(f"✗ SonarQube webhook test FAILED (status: {response.status_code})")
            return False

    except requests.exceptions.ConnectionError as e:
        print(f"✗ Connection error: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


# Тест health check endpoints
def test_health_endpoints(base_url: str):
    print(f"\n{'='*60}")
    print("Testing Health Endpoints")
    print(f"{'='*60}")

    endpoints = [
        ("/webhook/health", "TFS Webhook"),
        ("/sonarqube-webhook/health", "SonarQube Webhook")
    ]

    all_passed = True

    for endpoint, name in endpoints:
        url = f"{base_url}{endpoint}"
        print(f"\nTesting {name}: {url}")

        try:
            response = requests.get(url, verify=False)
            print(f"  Status: {response.status_code}")
            print(f"  Response: {response.json()}")

            if response.status_code == 200:
                print(f"  ✓ {name} health check PASSED")
            else:
                print(f"  ✗ {name} health check FAILED")
                all_passed = False

        except Exception as e:
            print(f"  ✗ Error: {e}")
            all_passed = False

    return all_passed


def main():
    parser = argparse.ArgumentParser(
        description="Test webhook endpoints for SAST PVS+Sonar Project Manager"
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default="http://localhost:8080",
        help="Base URL of the webhook service (default: http://localhost:8080)"
    )
    parser.add_argument(
        "--username",
        type=str,
        default="admin",
        help="Webhook username for Basic Auth (default: admin)"
    )
    parser.add_argument(
        "--password",
        type=str,
        default="admin",
        help="Webhook password for Basic Auth (default: admin)"
    )
    parser.add_argument(
        "--type",
        type=str,
        choices=["tfs", "tfvc", "sonarqube", "all", "health"],
        default="all",
        help="Type of webhook to test (default: all)"
    )
    parser.add_argument(
        "--project-key",
        type=str,
        default="test-project",
        help="SonarQube project key (default: test-project)"
    )
    parser.add_argument(
        "--project-name",
        type=str,
        default="Test Project",
        help="SonarQube project name (default: Test Project)"
    )
    parser.add_argument(
        "--sonar-secret",
        type=str,
        default=None,
        help="SonarQube webhook secret for signature (optional)"
    )
    parser.add_argument(
        "--verify-signature",
        action="store_true",
        help="Enable signature verification for SonarQube webhook"
    )

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print("SAST PVS+Sonar Webhook Test Script")
    print(f"{'='*60}")
    print(f"Base URL: {args.base_url}")
    print(f"Test Type: {args.type}")

    results = []

    if args.type in ["tfs", "all"]:
        results.append(test_tfs_git_webhook(
            args.base_url,
            args.username,
            args.password
        ))

    if args.type in ["tfvc", "all"]:
        results.append(test_tfvc_webhook(
            args.base_url,
            args.username,
            args.password
        ))

    if args.type in ["sonarqube", "all"]:
        results.append(test_sonarqube_webhook(
            args.base_url,
            project_key=args.project_key,
            project_name=args.project_name,
            secret=args.sonar_secret,
            verify_signature=args.verify_signature
        ))

    if args.type in ["health", "all"]:
        results.append(test_health_endpoints(args.base_url))

    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("✓ All tests PASSED")
        return 0
    else:
        print("✗ Some tests FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
