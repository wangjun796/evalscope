@echo off
rem 在 5 个分卷所在目录运行本脚本，合并出完整安装包
copy /b Next.AI.Draw.io.Setup.0.5.1.exe.00+Next.AI.Draw.io.Setup.0.5.1.exe.01+Next.AI.Draw.io.Setup.0.5.1.exe.02+Next.AI.Draw.io.Setup.0.5.1.exe.03+Next.AI.Draw.io.Setup.0.5.1.exe.04 Next.AI.Draw.io.Setup.0.5.1.exe
echo.
echo 合并完成，校验 MD5 应为:
type CHECKSUM.md5
echo 用命令验证: certutil -hashfile Next.AI.Draw.io.Setup.0.5.1.exe MD5
pause
