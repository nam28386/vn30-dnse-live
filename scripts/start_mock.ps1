$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start_local.ps1') -Mode MOCK
