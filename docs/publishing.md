# EvoLink-Bench 发布操作指南

本指南适用于 Windows PowerShell。源码仓库为 `BUAA-Self-Evolving/EvoLink-Bench`，版本为 `0.1.0`。发布前审阅文件和测试结果。源码、数据和各自许可证分别管理。

## 1. 准备工具和路径

安装 Python 3.11 或以上、Git 和 GitHub CLI。登录 GitHub 并确认账号有目标仓库写入权限。以下命令在同一个 PowerShell 窗口执行，路径按实际位置调整。

```powershell
$Source = '<path-to-EvoLink-Bench>'
$Work = Join-Path $env:TEMP ('EvoLink-publish-' + [guid]::NewGuid().ToString('N'))
$Remote = 'https://github.com/BUAA-Self-Evolving/EvoLink-Bench.git'
$Version = '0.1.0'
$Tag = 'v' + $Version
python --version
git --version
gh --version
gh auth status
if ($LASTEXITCODE -ne 0) { throw 'GitHub authentication failed' }
gh repo view BUAA-Self-Evolving/EvoLink-Bench --json isEmpty,defaultBranchRef,visibility,viewerPermission
if ($LASTEXITCODE -ne 0) { throw 'Repository check failed' }
```

首次推送流程适用于 `isEmpty` 为 `true` 的仓库。仓库已有提交时，先克隆并检查默认分支，再通过分支和 pull request 审阅，避免覆盖已有内容。

## 2. 复制并审阅源码

```powershell
New-Item -ItemType Directory -Path $Work | Out-Null
robocopy $Source $Work /E /XD .git .venv .venv-release __pycache__ .pytest_cache *.egg-info runs output outputs tmp private-data /XF '*.pyc' '*.log' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Copy failed: $LASTEXITCODE" }
Set-Location $Work
Get-ChildItem -Recurse -Force -File | Select-Object FullName,Length
```

审阅文件清单和文档，检查项目代码、上游来源与许可证。凭据、私有任务及答案、隐藏评分器、运行日志、检查点和历史成绩应留在受控位置。请核对 `CITATION.cff` 的作者信息。

## 3. 离线验证和构建

在源码工作目录以外创建环境和构建目录。网络安装依赖需要网络连接，smoke 测试本身不调用模型服务。

```powershell
$Venv = Join-Path $env:TEMP ('EvoLink-venv-' + [guid]::NewGuid().ToString('N'))
$Dist = Join-Path $env:TEMP ('EvoLink-dist-' + [guid]::NewGuid().ToString('N'))
$Py = Join-Path $Venv 'Scripts\python.exe'
python -m venv $Venv
if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed' }
& $Py -m pip install -e '.[gateway]' 'pytest>=8.3,<9' 'jsonschema>=4.23,<5' build
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& (Join-Path $Venv 'Scripts\evolink-bench.exe') --spec examples\smoke.json --output (Join-Path $env:TEMP ('EvoLink-smoke-' + [guid]::NewGuid().ToString('N')))
if ($LASTEXITCODE -ne 0) { throw 'Smoke test failed' }
& $Py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; review the failure before publishing' }
& $Py -m compileall -q evolink_bench baseline tools tests
if ($LASTEXITCODE -ne 0) { throw 'Compilation failed' }
& $Py -m build --outdir $Dist
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Get-ChildItem $Dist -File | Get-FileHash -Algorithm SHA256
```

Linux 和 Windows 的测试覆盖会因平台功能而异。GitHub Actions 在 Linux 上运行离线测试。检查 wheel 和 sdist 的文件清单，确认运行时文件、许可证与排除项符合预期。

## 4. 首次推送空仓库

确认文件清单和测试通过后执行。以下 `git add` 使用明确目录和文件清单。构建或测试生成物由 `.gitignore` 排除，提交前仍须检查暂存清单。

```powershell
Set-Location $Work
git init -b main
if ($LASTEXITCODE -ne 0) { throw 'Git initialization failed' }
git add -- .github .dockerignore .gitignore CITATION.cff CONTRIBUTING.md LICENSE MANIFEST.in THIRD_PARTY.md README.md pyproject.toml uv.lock baseline docs evolink_bench examples licenses sandbox schemas tests tools
if ($LASTEXITCODE -ne 0) { throw 'Staging failed' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Staged changes contain whitespace errors' }
git diff --cached --stat
git diff --cached --name-only
```

确认暂存清单后继续。Git 首次使用可能需要先设置 `git config --global user.name` 和 `git config --global user.email`。

```powershell
git commit -m "Release EvoLink-Bench $Version"
if ($LASTEXITCODE -ne 0) { throw 'Commit failed' }
git remote add origin $Remote
if ($LASTEXITCODE -ne 0) { throw 'Remote setup failed' }
git push -u origin main
if ($LASTEXITCODE -ne 0) { throw 'Push failed' }
git rev-parse HEAD
```

在 GitHub 网页检查 README 渲染、文件清单、许可证和 CI。确认提交后创建标签及 Release。

```powershell
git tag -a $Tag -m "EvoLink-Bench $Version"
if ($LASTEXITCODE -ne 0) { throw 'Tag creation failed' }
git push origin $Tag
if ($LASTEXITCODE -ne 0) { throw 'Tag push failed' }
gh release create $Tag --verify-tag --title "EvoLink-Bench $Version" --generate-notes
if ($LASTEXITCODE -ne 0) { throw 'Release creation failed' }
```

如需附加构建文件，可使用 `gh release upload`，同时发布核对过的 SHA-256。

## 5. Hugging Face 数据仓库

先在 Hugging Face 网站登录并创建 dataset 仓库。准备独立上传目录，放入经过审阅的数据卡、许可证和具体获准发布的文件。公开数据卡和许可证通知应放在独立的 Hugging Face 上传目录中。上传目录只包含已批准公开的说明文件和数据文件，不包含私有题目、答案、隐藏评分器或运行产物。各来源数据的许可和再分发条件须逐项核对，代码的 MIT 许可证不自动覆盖数据。

在隔离环境中安装 Hugging Face 工具，按提示登录。令牌只输入认证提示，勿写入文件或命令历史。先将仓库设为私有，通过网页上传发布目录内文件，检查文件列表、版本、来源和数据卡，然后根据已确认的发布范围在网页仓库设置中调整可见性。记录提交 ID、文件列表、文件大小和 SHA-256，并从固定提交重新下载核对。公开后在未登录浏览器检查可访问性。

```powershell
$HFDir = '<path-to-HF-dataset-card>'
Get-ChildItem $HFDir -Recurse -File | Select-Object FullName,Length
Get-ChildItem $HFDir -Recurse -File | Get-FileHash -Algorithm SHA256
```

## 6. 保存发布记录

记录源码提交、标签、Release 地址、测试结果、构建包文件名及 SHA-256，以及数据仓库名称、提交、文件清单、校验值和各组件许可证。源代码版本与数据版本分别记录。
