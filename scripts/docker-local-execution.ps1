[CmdletBinding()]
param(
    [ValidateSet('Start', 'Resume', 'Status', 'RestoreRemote')]
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
    return @('-f', 'docker-compose.yml')
}

function Assert-LocalExecutionMode {
    $probe = "from app.config.setting import settings; import json; print(json.dumps({'mode': settings.CODE_INTERPRETER_KIND, 'allow_local': settings.ALLOW_LOCAL_CODE_EXECUTION, 'e2b_configured': bool(settings.E2B_API_KEY)}))"
    $result = (& docker compose @(Get-LocalComposeArguments) exec -T backend uv run python -c $probe | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw '无法读取后端实际执行配置。'
    }
    try {
        $config = $result | ConvertFrom-Json
    } catch {
        throw "后端执行配置输出不是 JSON：$result"
    }
    if ($config.mode -ne 'auto' -or -not $config.allow_local) {
        throw "本地自动模式未生效：mode=$($config.mode), allow_local=$($config.allow_local)"
    }
    Write-Host ("本地自动模式已生效：mode={0}, allow_local={1}, e2b_configured={2}" -f $config.mode, $config.allow_local, $config.e2b_configured)
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
        'RestoreRemote' { Invoke-Compose ((Get-RemoteComposeArguments) + @('up', '-d', '--wait')); docker compose ps }
    }
} finally {
    Pop-Location
}
