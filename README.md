===========================
 SUNSHINE PAIR CLI TOOL
===========================

A lightweight PowerShell script to manage pairing between
Moonlight clients and a Sunshine host using Sunshine's REST API.

Author: YOUR NAME
Repository: https://github.com/zenixbot0101/sunshine-pair-cli
License: MIT

---------------------------
 REQUIREMENTS
---------------------------
- Sunshine running on your system
- PowerShell 5.1+ (Windows) or PowerShell Core (Linux/macOS)
- Sunshine API enabled (default ports: 47989 HTTP / 47990 HTTPS)

---------------------------
 CONFIGURATION
---------------------------
Open the file sunshine-pair.ps1 and edit the following lines:

$SunshineHost = "https://localhost:47990"
$User = "admin"
$Pass = "yourpassword"

If you have enabled `allow_unauthenticated_localhost = true` in sunshine.conf,
you can remove the User/Pass lines.

---------------------------
 USAGE
---------------------------

1. Open PowerShell as Administrator.
2. Allow script execution (temporary):
   Set-ExecutionPolicy Bypass -Scope Process

3. Run the script with one of the following commands:

   Pair a device (will prompt for PIN):
     .\sunshine-pair.ps1 pair

   Pair directly with PIN:
     .\sunshine-pair.ps1 pair 1234

   List all paired clients:
     .\sunshine-pair.ps1 list

   Unpair a client by UUID:
     .\sunshine-pair.ps1 unpair

   Unpair all clients:
     .\sunshine-pair.ps1 unpair-all

---------------------------
 EXAMPLES
---------------------------

> .\sunshine-pair.ps1 pair
Enter PIN (from Moonlight): 1234
🔗 Sending pairing request to Sunshine...
✅ Pairing result: True

> .\sunshine-pair.ps1 list
📋 Paired clients:
uuid        name           last_connected
----        ----           ---------------
A1B2C3D4    LivingRoomPC   2025-10-03T15:42:00Z

---------------------------
 NOTES
---------------------------
- Sunshine must be running before pairing.
- Make sure the correct API port is used (default HTTPS 47990).
- Works on both Windows and Linux systems.

---------------------------
 LICENSE
---------------------------
This project is licensed under the MIT License.
You may freely use, modify, and distribute it.

