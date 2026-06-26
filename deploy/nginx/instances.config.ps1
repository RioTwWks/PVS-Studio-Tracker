# Общие настройки пула uvicorn за nginx (dot-source из других скриптов).
@{
    # Минимум healthy backend'ов в upstream (всегда должно быть >= 2).
    MinHealthyInstances = 2

    # Сколько служб держать запущенными в штатном режиме (остальные — hot spare).
    DesiredRunningInstances = 2

    # Пул портов / служб PVS-Tracker-<port>. Порядок = приоритет запуска.
    PortPool = @(8081, 8082, 8083, 8084)

    ServicePrefix = 'PVS-Tracker'

    # Каталог nginx (prefix): conf/, logs/, nginx.exe
    NginxRoot = 'C:\nginx'

    # Каталог nginx conf (upstream-active.conf и drained-ports.txt рядом с nginx.conf).
    NginxConfDir = 'C:\nginx\conf'

    NginxExe = 'C:\nginx\nginx.exe'

    # Таймаут readiness при старте spare.
    ReadyTimeoutSeconds = 120

    # Пауза drain перед рестартом при rolling update.
    DrainSeconds = 35
}
