@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
cl /nologo /std:c++17 /EHsc /W4 /WX /utf-8 /permissive- /MT /O2 /I "D:\Code\SWITCH_TRANSLATER\decompiler\stubs" "D:\Code\SWITCH_TRANSLATER\decompiler\output\e2e_switchrecomp_recompiled_runner.cpp" "D:\Code\SWITCH_TRANSLATER\decompiler\stubs\horizon_os\horizon_os.cpp" "D:\Code\SWITCH_TRANSLATER\decompiler\stubs\horizon_os\ipc.cpp" /Fe:"D:\Code\SWITCH_TRANSLATER\decompiler\output\e2e_switchrecomp.exe"
exit /b %ERRORLEVEL%
