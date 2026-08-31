#Requires -Version 5.1
<#
Sobe o dash-tracken localmente: cria o venv se faltar, instala/atualiza
dependencias e roda o Streamlit. Uso: .\scripts\run_local.ps1
#>

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    Write-Host "Criando ambiente virtual (.venv)..."
    python -m venv .venv
}

Write-Host "Instalando dependencias..."
& $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt

Write-Host "Iniciando Streamlit em http://localhost:8501 ..."
& $venvPython -m streamlit run app.py
