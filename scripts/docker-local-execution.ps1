[CmdletBinding()]
param(
    [ValidateSet('Start', 'Resume', 'Status', 'UseRemote', 'RestoreRemote')]
    [string]$Action = 'Start',
    [string]$TaskId,
    [string]$ApiBase = 'http://127.0.0.1:5173/api'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$taskRoot = Join-Path $repoRoot 'backend\project\work_dir'

function Invoke-Compose {
    param([string[]]$Arguments)
    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose 命令失败（退出码 $LASTEXITCODE）：docker compose $($Arguments -join ' ')"
    }
}

function Get-LocalComposeArguments {
    return @(
        '-f', 'docker-compose.yml',
        '-f', 'docker-compose.override.yml',
        '-f', 'docker-compose.local-execution.yml'
    )
}

function Get-RemoteComposeArguments {
    return @(
        '-f', 'docker-compose.yml',
        '-f', 'docker-compose.override.yml'
    )
}

function Assert-LocalExecutionMode {
    $probe = "from app.config.setting import settings; import json; print(json.dumps({'mode': settings.CODE_INTERPRETER_KIND, 'allow_local': settings.ALLOW_LOCAL_CODE_EXECUTION, 'e2b_configured': bool(settings.E2B_API_KEY)}))"
    $result = (& docker compose @(Get-LocalComposeArguments) exec -T backend /app/.venv/bin/python -c $probe | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw '无法读取后端实际执行配置。'
    }
    try {
        $config = $result | ConvertFrom-Json
    } catch {
        throw "后端执行配置输出不是 JSON：$result"
    }
    if ($config.mode -ne 'local' -or -not $config.allow_local) {
        throw "可信本地模式未生效：mode=$($config.mode), allow_local=$($config.allow_local)"
    }
    Write-Host ("可信本地模式已生效：mode={0}, allow_local={1}, e2b_configured={2}" -f $config.mode, $config.allow_local, $config.e2b_configured)
}

function Test-RemoteE2BConfigured {
    $raw = (& docker compose @(Get-RemoteComposeArguments) config --format json | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw '无法解析远程 Compose 配置。'
    }
    try {
        $config = $raw | ConvertFrom-Json
        $value = $config.services.backend.environment.E2B_API_KEY
    } catch {
        throw '远程 Compose 配置格式无效。'
    }
    return -not [string]::IsNullOrWhiteSpace([string]$value)
}

function Start-RemoteMode {
    if (-not (Test-RemoteE2BConfigured)) {
        throw '未配置 E2B_API_KEY，拒绝把当前可信本地执行切换为不可用的 remote 模式。'
    }
    Write-Warning '正在显式切换到 E2B remote；这不是本机默认恢复动作。'
    Invoke-Compose ((Get-RemoteComposeArguments) + @('up', '-d', '--wait'))
}

function Start-LocalMode {
    Invoke-Compose ((Get-LocalComposeArguments) + @('up', '-d', '--wait'))
    Assert-LocalExecutionMode
}

function Get-TaskFromApi {
    param([Parameter(Mandatory)][string]$Id)
    $tasks = Invoke-RestMethod -Method Get -Uri "$ApiBase/tasks"
    $task = @($tasks) | Where-Object { $_.task_id -eq $Id } | Select-Object -First 1
    if ($null -eq $task) {
        throw "找不到任务 $Id。"
    }
    return $task
}

function Resume-Task {
    if ([string]::IsNullOrWhiteSpace($TaskId)) {
        throw 'Resume 操作必须提供 -TaskId。'
    }
    $taskDir = Join-Path $taskRoot $TaskId
    if (-not (Test-Path -LiteralPath (Join-Path $taskDir 'checkpoint.json'))) {
        throw "任务 $TaskId 没有 checkpoint.json，不能走续传路径。"
    }
    Start-LocalMode
    $task = Get-TaskFromApi -Id $TaskId
    if ($task.status -eq 'completed' -or $task.has_result) {
        Write-Host "任务 $TaskId 已完成，不重复续传。"
        return
    }
    $response = Invoke-RestMethod -Method Post -Uri "$ApiBase/modeling/$TaskId/resume"
    Write-Host ("续传请求已接受：{0}" -f (($response | ConvertTo-Json -Compress)))
}

function Show-Status {
    if (-not [string]::IsNullOrWhiteSpace($TaskId)) {
        $task = Get-TaskFromApi -Id $TaskId
        $task | Select-Object task_id, status, has_checkpoint, has_result | ConvertTo-Json -Compress
    }
    docker compose ps
}

Push-Location $repoRoot
try {
    switch ($Action) {
        'Start' { Start-LocalMode }
        'Resume' { Resume-Task }
        'Status' { Show-Status }
        'UseRemote' { Start-RemoteMode; docker compose @(Get-RemoteComposeArguments) ps }
        'RestoreRemote' {
            Write-Warning '-Action RestoreRemote 已弃用；它现在与 UseRemote 相同，并会先验证 E2B_API_KEY。'
            Start-RemoteMode
            docker compose @(Get-RemoteComposeArguments) ps
        }
    }
} finally {
    Pop-Location
}
