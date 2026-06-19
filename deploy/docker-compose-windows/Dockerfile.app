# escape=`
# Windows container image for PVS-Studio Tracker (uvicorn + workers).
# Build on Windows Server with Docker Engine (Windows containers mode).
#
#   docker build -f deploy/docker-compose-windows/Dockerfile.app -t pvs-tracker-app:local .

ARG WINDOWS_VERSION=ltsc2019-amd64
FROM mcr.microsoft.com/windows/servercore:${WINDOWS_VERSION}

ARG PYTHON_VERSION=3.12.10
ARG PYTHON_INSTALLER=python-3.12.10-amd64.exe

ENV PYTHON_VERSION=${PYTHON_VERSION}
ENV PYTHON_INSTALLER=${PYTHON_INSTALLER}

SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

RUN $pyUrl = \"https://www.python.org/ftp/python/$env:PYTHON_VERSION/$env:PYTHON_INSTALLER\"; `
    Invoke-WebRequest -Uri $pyUrl -OutFile $env:PYTHON_INSTALLER; `
    Start-Process -FilePath .\\$env:PYTHON_INSTALLER -ArgumentList @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_pip=1') -Wait; `
    Remove-Item -Force $env:PYTHON_INSTALLER; `
    python --version; `
    python -m pip install --upgrade pip

WORKDIR C:/app

COPY pyproject.toml ./
COPY pvs_tracker ./pvs_tracker
COPY static ./static

RUN python -m pip install --no-cache-dir . psycopg2-binary

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# gunicorn на Windows недоступен; один uvicorn на контейнер, масштабирование — app-1/app-2 за nginx.
CMD ["python", "-m", "uvicorn", "pvs_tracker.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "30"]
