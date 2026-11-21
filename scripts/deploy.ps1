# 一键触发 Render 部署并等待结果
# 用法：
#   .\scripts\deploy.ps1 -Key rnd_xxx
#   或先设环境变量 $env:RENDER_API_KEY，再 .\scripts\deploy.ps1
param(
  [string]$Key = $env:RENDER_API_KEY,
  [string]$ServiceId = "srv-dc0leom7bikc73b5q2gg",
  [string]$HealthUrl = "https://zhiwei-u0jc.onrender.com/health",
  [switch]$NoWait
)

if (-not $Key) {
  Write-Host "缺少 Render API Key。用法： .\scripts\deploy.ps1 -Key rnd_xxx" -ForegroundColor Red
  exit 1
}

$headers = @{ Authorization = "Bearer $Key"; "Content-Type" = "application/json" }
$body = '{"clearCache":"do_not_clear"}'

try {
  $deploy = Invoke-RestMethod -Method Post `
    -Uri "https://api.render.com/v1/services/$ServiceId/deploys" `
    -Headers $headers -Body $body -TimeoutSec 60
} catch {
  Write-Host "触发失败：$($_.Exception.Message)" -ForegroundColor Red
  exit 1
}

Write-Host "已触发部署：$($deploy.id)" -ForegroundColor Green
if ($NoWait) { exit 0 }

$deadline = (Get-Date).AddMinutes(15)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 15
  $d = Invoke-RestMethod -Uri "https://api.render.com/v1/services/$ServiceId/deploys/$($deploy.id)" -Headers $headers
  Write-Host ("  状态：{0}" -f $d.status)
  if ($d.status -eq "live") { break }
  if ($d.status -in @("build_failed", "update_failed", "canceled")) {
    Write-Host "部署失败，去 Render 控制台看构建日志。" -ForegroundColor Red
    exit 1
  }
}

try {
  $h = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 90
  Write-Host ("线上状态：{0} | 数据库：{1} | 模型：{2}" -f $h.status, $h.config.database, $h.config.llm_provider) -ForegroundColor Green
} catch {
  Write-Host "健康检查失败：$($_.Exception.Message)" -ForegroundColor Yellow
}
