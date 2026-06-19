# escape=`
# Windows container image for PVS-Studio Tracker (uvicorn + workers).
# MinGit нужен для GitPython: clone/pull в CI webhooks и inline code viewer.
#
# Online build:
#   docker build -f deploy/docker-compose-windows/Dockerfile.app -t pvs-tracker-app:local .
#
# Offline build (без сети в build-контейнере):
#   docker build -f deploy/docker-compose-windows/Dockerfile.app --build-arg USE_OFFLINE_DEPS=1 .
#
# Корпоративный proxy (для Invoke-WebRequest и pip внутри build-контейнера):
#   docker build ... --build-arg HTTPS_PROXY=http://proxy.corp:8080 --build-arg HTTP_PROXY=http://proxy.corp:8080

ARG WINDOWS_VERSION=ltsc2019-amd64
FROM mcr.microsoft.com/windows/servercore:${WINDOWS_VERSION}

ARG PYTHON_VERSION=3.12.10
ARG PYTHON_INSTALLER=python-3.12.10-amd64.exe
ARG GIT_VERSION=2.47.1.windows.2
ARG GIT_ZIP=MinGit-2.47.1.2-64-bit.zip
ARG USE_OFFLINE_DEPS=0
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY

ENV PYTHON_VERSION=${PYTHON_VERSION}
ENV PYTHON_INSTALLER=${PYTHON_INSTALLER}
ENV GIT_VERSION=${GIT_VERSION}
ENV GIT_ZIP=${GIT_ZIP}
ENV USE_OFFLINE_DEPS=${USE_OFFLINE_DEPS}
ENV HTTP_PROXY=${HTTP_PROXY}
ENV HTTPS_PROXY=${HTTPS_PROXY}
ENV NO_PROXY=${NO_PROXY}

SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

COPY deploy/docker-compose-windows/build-deps/ C:/build-deps/

RUN function Save-RemoteFile([string]$Url, [string]$OutFile) { `
      $proxy = if ($env:HTTPS_PROXY) { $env:HTTPS_PROXY } elseif ($env:HTTP_PROXY) { $env:HTTP_PROXY } else { $null }; `
      if ($proxy) { `
        Write-Host \"Downloading via proxy $proxy ...\"; `
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -Proxy $proxy; `
      } else { `
        Invoke-WebRequest -Uri $Url -OutFile $OutFile; `
      } `
    }; `
    $offline = ($env:USE_OFFLINE_DEPS -eq '1'); `
    $pyLocal = Join-Path 'C:\build-deps' $env:PYTHON_INSTALLER; `
    $gitLocal = Join-Path 'C:\build-deps' $env:GIT_ZIP; `
    if ($offline -and -not (Test-Path $pyLocal)) { throw \"Offline build: missing $pyLocal\" }; `
    if ($offline -and -not (Test-Path $gitLocal)) { throw \"Offline build: missing $gitLocal\" }; `
    if ($offline) { `
        Copy-Item $pyLocal .\\$env:PYTHON_INSTALLER; `
    } else { `
        $pyUrl = \"https://www.python.org/ftp/python/$env:PYTHON_VERSION/$env:PYTHON_INSTALLER\"; `
        Save-RemoteFile -Url $pyUrl -OutFile $env:PYTHON_INSTALLER; `
    }; `
    $proc = Start-Process -FilePath .\\$env:PYTHON_INSTALLER -ArgumentList @('/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_pip=1') -Wait -PassThru; `
    if ($proc.ExitCode -ne 0) { throw \"Python installer failed with exit code $($proc.ExitCode)\" }; `
    Remove-Item -Force $env:PYTHON_INSTALLER; `
    $pyExe = 'C:\\Program Files\\Python312\\python.exe'; `
    if (-not (Test-Path $pyExe)) { `
        $found = Get-ChildItem 'C:\\Program Files' -Filter python.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1; `
        if (-not $found) { throw 'python.exe not found after installer finished' }; `
        $pyExe = $found.FullName; `
    }; `
    $pyDir = Split-Path $pyExe -Parent; `
    $env:Path = \"$pyDir;$pyDir\Scripts;\" + $env:Path; `
    Write-Host \"Using Python at $pyExe\"; `
    & $pyExe --version; `
    & $pyExe -m pip install --upgrade pip; `
    New-Item -ItemType Directory -Force -Path C:\\Docker | Out-Null; `
    Set-Content -Path C:\\Docker\\python-path.txt -Value $pyExe -NoNewline; `
    if ($offline) { `
        Copy-Item $gitLocal .\\$env:GIT_ZIP; `
    } else { `
        $gitUrl = \"https://github.com/git-for-windows/git/releases/download/v$env:GIT_VERSION/$env:GIT_ZIP\"; `
        Save-RemoteFile -Url $gitUrl -OutFile $env:GIT_ZIP; `
    }; `
    $gitStaging = 'C:\\MinGit-staging'; `
    if (Test-Path C:\\MinGit) { Remove-Item C:\\MinGit -Recurse -Force }; `
    if (Test-Path $gitStaging) { Remove-Item $gitStaging -Recurse -Force }; `
    Expand-Archive -Path $env:GIT_ZIP -DestinationPath $gitStaging; `
    Remove-Item -Force $env:GIT_ZIP; `
    $gitExe = Get-ChildItem $gitStaging -Filter git.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1; `
    if (-not $gitExe) { throw 'git.exe not found after MinGit extract (check MinGit zip in build-deps)' }; `
    if ($gitExe.Directory.Name -eq 'cmd') { `
        $gitRoot = $gitExe.Directory.Parent.FullName; `
    } else { `
        $gitRoot = $gitExe.Directory.FullName; `
    }; `
    New-Item -ItemType Directory -Force -Path C:\\MinGit | Out-Null; `
    Copy-Item -Path (Join-Path $gitRoot '*') -Destination C:\\MinGit -Recurse -Force; `
    Remove-Item $gitStaging -Recurse -Force; `
    $gitExePath = 'C:\\MinGit\\cmd\\git.exe'; `
    if (-not (Test-Path $gitExePath)) { $gitExePath = $gitExe.FullName }; `
    $env:Path = 'C:\\MinGit\\cmd;C:\\MinGit\\mingw64\\bin;' + $env:Path; `
    Write-Host \"Using Git at $gitExePath\"; `
    & $gitExePath --version

WORKDIR C:/app

COPY pyproject.toml ./
COPY pvs_tracker ./pvs_tracker
COPY static ./static

ENV PATH="C:\\Program Files\\Python312;C:\\Program Files\\Python312\\Scripts;C:\\MinGit\\cmd;C:\\MinGit\\mingw64\\bin;${PATH}"

RUN python -m pip install --no-cache-dir . psycopg2-binary

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "pvs_tracker.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "30"]
