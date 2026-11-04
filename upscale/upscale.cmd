@echo off
rem Drag a video onto this file to upscale it with AI (Real-ESRGAN on your graphics card).
if "%~1"=="" (echo Drag a video file onto upscale.cmd. & pause & exit /b)
set T=4k
set /p T=Size: 2k, 4k or 8k? [4k] 
set M=photo
set /p M=Video type: photo (camera) or anime? [photo] 
python "%~dp0upscale.py" "%~1" --to %T% --model %M%
pause
