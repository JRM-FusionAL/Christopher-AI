; Christopher Dev Macros — AutoHotkey v2
; Install: https://www.autohotkey.com/
; Save as: christopher-macros.ahk
; Run: double-click or add to startup

#Requires AutoHotkey v2.0

; ── Text Expansion ────────────────────────────────────────────────────────────
; Type these anywhere, they expand instantly

:*:;;bi::http://localhost:8101
:*:;;api::http://localhost:8102
:*:;;content::http://localhost:8103
:*:;;fusional::http://localhost:8009
:*:;;llama::http://localhost:8080
:*:;;cd1::cd /home/oledad/voice-ai-local
:*:;;cd2::cd /mnt/c/Users/puddi/Projects/mcp-consulting-kit
:*:;;cd3::cd /mnt/c/Users/puddi/Projects/FusionAL

; ── Command Macros (Ctrl+Alt+key) ─────────────────────────────────────────────

; Ctrl+Alt+C = start Christopher chat mode
^!c:: {
    cmd := "python3 /home/oledad/voice-ai-local/christopher.py --chat --no-server"
    A_Clipboard := cmd
    Send "^v"
}

; Ctrl+Alt+L = start llama-server with 3B model
^!l:: {
    cmd := "~/llama.cpp/build/bin/llama-server -m ~/llama.cpp/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf -ngl 99 -t 4 -c 2048 --host 127.0.0.1 --port 8080 --log-disable"
    A_Clipboard := cmd
    Send "^v"
}

; Ctrl+Alt+M = start llama-server with Mistral 7B
^!m:: {
    cmd := "~/llama.cpp/build/bin/llama-server -m ~/llama.cpp/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf -ngl 24 -t 4 -c 512 --host 127.0.0.1 --port 8080 --log-disable"
    A_Clipboard := cmd
    Send "^v"
}

; Ctrl+Alt+S = launch all Windows servers
^!s:: {
    Run "C:\Users\puddi\Projects\mcp-consulting-kit\launch-all-servers.bat"
}

; Ctrl+Alt+H = health check all servers
^!h:: {
    cmd := "curl -s http://localhost:8101/health & curl -s http://localhost:8102/health & curl -s http://localhost:8103/health & curl -s http://localhost:8009/health"
    A_Clipboard := cmd
    Send "^v"
}

; Ctrl+Alt+K = rotate API key (generates new one, copies to clipboard)
^!k:: {
    cmd := "python3 -c `"import secrets; k=secrets.token_hex(16); print(k)`""
    A_Clipboard := cmd
    Send "^v"
}

; Ctrl+Alt+G = git status + push current repo
^!g:: {
    cmd := "git add -A && git status"
    A_Clipboard := cmd
    Send "^v"
}

; Ctrl+Alt+P = git push
^!p:: {
    cmd := "git push origin main"
    A_Clipboard := cmd
    Send "^v"
}

; Ctrl+Alt+D = docker compose up
^!d:: {
    Run "cmd /k cd /d C:\Users\puddi\Projects\mcp-consulting-kit && docker compose up"
}

; ── Window Switching (Win+number) ─────────────────────────────────────────────

; Win+1 = focus or open WSL terminal
#1:: {
    if WinExist("ahk_exe wsl.exe") || WinExist("2FkinAwesome")
        WinActivate
    else
        Run "wsl"
}

; Win+2 = focus Windows Terminal / PowerShell
#2:: {
    if WinExist("ahk_exe WindowsTerminal.exe")
        WinActivate "ahk_exe WindowsTerminal.exe"
    else if WinExist("ahk_exe powershell.exe")
        WinActivate "ahk_exe powershell.exe"
    else
        Run "powershell"
}

; Win+3 = focus VS Code
#3:: {
    if WinExist("ahk_exe Code.exe")
        WinActivate "ahk_exe Code.exe"
    else
        Run "code C:\Users\puddi\Projects"
}
