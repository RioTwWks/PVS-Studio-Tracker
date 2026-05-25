# Тест импортов для переработанных модулей

import sys

# Тест импорта элементов из модуля
def test_import(module_name, items=None):
    try:
        if items:
            for item in items:
                exec(f"from {module_name} import {item}")
                print(f"✓ {module_name}.{item}")
        else:
            exec(f"import {module_name}")
            print(f"✓ {module_name}")
        return True
    except Exception as e:
        print(f"✗ {module_name}: {e}")
        return False

print("Тест импортов...\n")

all_ok = True

# Тест модуля webhooks
print("Тест app.webhooks:")
all_ok &= test_import("app.webhooks", [
    "handle_webhook",
    "health_check",
    "trigger_jenkins_job",
    "update_last_changeset"
])

# Тест сервисов
print("\nTesting app.services:")
all_ok &= test_import("app.services", [
    "check_git_changes",
    "check_tfvc_changes",
    "check_tfvc_merge",
    "trigger_jenkins_build",
    "process_sonarqube_webhook",
    "get_jira_client",
    "create_jira_issue"
])

print("\n" + "="*40)
if all_ok:
    print("✓ Всё успешно импортировано")
    sys.exit(0)
else:
    print("✗ Некоторые импорты провалились")
    sys.exit(1)
