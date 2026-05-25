@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==========================================
echo    AZFA Web - تطبيق إدارة الطلاب
echo ==========================================
echo.

REM التأكد من وجود Python
where python >nul 2>nul
if errorlevel 1 (
    echo [خطأ] Python غير مثبت. حمّله من https://python.org
    pause
    exit /b 1
)

REM إنشاء البيئة الافتراضية إذا غير موجودة
if not exist ".venv\Scripts\python.exe" (
    echo [+] إنشاء بيئة افتراضية...
    python -m venv .venv
)

REM تثبيت المتطلبات
echo [+] تثبيت/تحديث المتطلبات...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

REM طباعة IP الشبكة للوصول من الموبايل
echo.
echo ──────────────────────────────────────────
echo 🌐 افتح المتصفح على: http://localhost:5000
echo 📱 من الموبايل، استخدم أحد العناوين التالية:
for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /C:"IPv4"') do echo     http://%%i:5000
echo ──────────────────────────────────────────
echo.

REM التشغيل
".venv\Scripts\python.exe" app.py
pause
