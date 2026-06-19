# escape=`
# Windows container image for PVS-Studio Tracker (uvicorn + workers).
# MinGit нужен для GitPython: clone/pull в CI webhooks и inline code viewer.
#
# Online build (нужен DNS в build-контейнере):
#   docker build -f deploy/docker-compose-windows/Dockerfile.app -t pvs-tracker-app:local .
#
# Offline build — положите установщики в deploy/docker-compose-windows/build-deps/:
#   docker build -f deploy/docker-compose-windows/Dockerfile.app --build-arg USE_OFFLINE_DEPS=1 .

ARG WINDOWS_VERSION=ltsc2019-amd64
FROM mcr.microsoft.com/windows/servercore:${WINDOWS_VERSION}

ARG PYTHON_VERSION=3.12.10
ARG PYTHON_INSTALLER=python-3.12.10-amd64.exe
ARG GIT_VERSION=2.47.1.windows.2
ARG GIT_ZIP=MinGit-2.47.1.2-64-bit.zip
ARG USE_OFFLINE_DEPS=0

ENV PYTHON_VERSION=${PYTHON_VERSION}
ENV PYTHON_INSTALLER=${PYTHON_INSTALLER}
ENV GIT_VERSION=${GIT_VERSION}
ENV GIT_ZIP=${GIT_ZIP}
ENV USE_OFFLINE_DEPS=${USE_OFFLINE_DEPS}

SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

# Копируем опциональные установщики (для offline-сборки без DNS в контейнере).
COPY deploy/docker-compose-windows/build-deps/ C:/build-deps/

RUN $offline = ($env:USE_OFFLINE_DEPS -eq '1'); `
    $pyLocal = Join-Path 'C:\build-deps' $env:PYTHON_INSTALLER; `
    $gitLocal = Join-Path 'C:\build-deps' $env:GIT_ZIP; `
    if ($offline -and -not (Test-Path $pyLocal)) { throw \"Offline build: missing $pyLocal\" }; `
    if ($offline -and -not (Test-Path $gitLocal)) { throw \"Offline build: missing $gitLocal\" }; `
    if ($offline) { `
        Copy-Item $pyLocal .\\$env:PYTHON_INSTALLER; `
    } else { `
        $pyUrl = \"https://www.python.org/ftp/python/$env:PYTHON_VERSION/$env:PYTHON_INSTALLER\"; `
        Invoke-WebRequest -Uri $pyUrl -OutFile $env:PYTHON_INSTALLER; `
    }; `
    Start-Process -FilePath .\\$env:PYTHON_INSTALLER -ArgumentList @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_pip=1') -Wait; `
    Remove-Item -Force $env:PYTHON_INSTALLER; `
    python --version; `
    python -m pip install --upgrade pip; `
    if ($offline) { `
        Copy-Item $gitLocal .\\$env:GIT_ZIP; `
    } else { `
        $gitUrl = \"https://github.com/git-for-windows/git/releases/download/v$env:GIT_VERSION/$env:GIT_ZIP\"; `
        Invoke-WebRequest -Uri $gitUrl -OutFile $env:GIT_ZIP; `
    }; `
    Expand-Archive -Path $env:GIT_ZIP -DestinationPath C:\MinGit; `
    Remove-Item -Force $env:GIT_ZIP; `
    git --version

WORKDIR C:/app

COPY pyproject.toml ./
COPY pvs_tracker ./pvs_tracker
COPY static ./static

RUN python -m pip install --no-cache-dir . psycopg2-binary

ENV PATH="C:\\MinGit\\cmd;C:\\MinGit\\mingw64\\bin;${PATH}"
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# gunicorn на Windows недоступен; один uvicorn на контейнер, масштабирование — app-1/app-2 за nginx.
CMD ["python", "-m", "uvicorn", "pvs_tracker.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "30"]
