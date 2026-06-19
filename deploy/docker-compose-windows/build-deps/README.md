# Offline build dependencies (optional)

Если при `docker build` внутри контейнера **нет DNS/интернета**, скачайте установщики **на хосте Windows** и положите сюда:

| Файл | Откуда скачать |
|------|----------------|
| `python-3.12.10-amd64.exe` | https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe |
| `MinGit-2.47.1.2-64-bit.zip` | https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/MinGit-2.47.1.2-64-bit.zip |
| `postgresql-16.6-1-windows-x64-binaries.zip` | https://get.enterprisedb.com/postgresql/postgresql-16.6-1-windows-x64-binaries.zip |

Имена должны совпадать с `PYTHON_INSTALLER` и `GIT_ZIP` в `Dockerfile.app` (или передайте свои через `--build-arg`).

```powershell
docker compose build --build-arg USE_OFFLINE_DEPS=1
```

Без файлов в этой папке сборка пытается скачать их из интернета (нужен рабочий DNS в build-контейнере).
