param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("pair","list","unpair","unpair-all")]
    [string]$Action,

    [Parameter(Position=1)]
    [string]$Value
)

$SunshineHost = "https://localhost:47990"
$User = "admin"
$Pass = "yourpassword"

$AuthHeader = @{
    Authorization = 'Basic ' + [Convert]::ToBase64String(
        [Text.Encoding]::ASCII.GetBytes("$User`:$Pass")
    )
}
$Headers = @{
    "Content-Type" = "application/json"
} + $AuthHeader

switch ($Action) {

    "pair" {
        if (-not $Value) {
            $Value = Read-Host "Enter PIN (from Moonlight)"
        }
        $Body = @{
            pin  = $Value
            name = $env:COMPUTERNAME
        } | ConvertTo-Json

        Write-Host "🔗 Sending pairing request to Sunshine..."
        try {
            $res = Invoke-RestMethod -SkipCertificateCheck -Uri "$SunshineHost/api/pin" -Method POST -Headers $Headers -Body $Body
            Write-Host "✅ Pairing result: $res"
        } catch {
            Write-Host "❌ Error: $($_.Exception.Message)"
        }
    }

    "list" {
        Write-Host "📋 Paired clients:"
        try {
            $res = Invoke-RestMethod -SkipCertificateCheck -Uri "$SunshineHost/api/clients/list" -Method GET -Headers $Headers
            if ($res) {
                $res | Format-Table
            } else {
                Write-Host "⚠️ No clients found."
            }
        } catch {
            Write-Host "❌ Error: $($_.Exception.Message)"
        }
    }

    "unpair" {
        if (-not $Value) {
            $Value = Read-Host "Enter client UUID to unpair"
        }
        $Body = @{ uuid = $Value } | ConvertTo-Json
        Write-Host "🧹 Unpairing client UUID $Value ..."
        try {
            $res = Invoke-RestMethod -SkipCertificateCheck -Uri "$SunshineHost/api/clients/unpair" -Method POST -Headers $Headers -Body $Body
            Write-Host "✅ Result: $res"
        } catch {
            Write-Host "❌ Error: $($_.Exception.Message)"
        }
    }

    "unpair-all" {
        Write-Host "🧨 Unpairing all clients..."
        try {
            $res = Invoke-RestMethod -SkipCertificateCheck -Uri "$SunshineHost/api/clients/unpair-all" -Method POST -Headers $Headers
            Write-Host "✅ Result: $res"
        } catch {
            Write-Host "❌ Error: $($_.Exception.Message)"
        }
    }
}
