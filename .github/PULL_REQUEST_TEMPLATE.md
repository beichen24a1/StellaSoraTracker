## 变更说明

<!-- 做了什么、为什么做。关联 Issue 用 Fixes #123 / Closes #123。 -->

## 影响范围

- [ ] 引擎（`stellasora_toolkit/`：内存读取、归档、统计、上传）
- [ ] 前端（`frontend/`：Vue 视图、Electron 窗口与 IPC）
- [ ] 打包与安装（`*.spec`、`installer/`、`build_*.ps1`、`tools/`）
- [ ] 资源（`assets/`、`resources.zip`、`resource_manifest*.json`）
- [ ] 更新清单与版本号（`app_update*.json`、`pyproject.toml`、`frontend/package.json`）
- [ ] 文档（`README.md`、`docs/`、`AGENTS.md`）

## 验证

至少跑与改动相关的项，并在下面写实际结果：

- [ ] `python tools/run_tests.py`
- [ ] `cd frontend && npm run build`（vue-tsc 类型检查 + vite 构建）
- [ ] `cd frontend && npm run test`（vitest）
- [ ] 实机验证：游戏内读取 / 上传蕾姆 / 更新安装 / 打包产物启动

补充说明（失败项、跳过原因、环境差异）：

## 更新日志

<!--
用户可见的改动必须留档，任选其一：
- 在 docs/releases/<版本>.md 写一条；
- 在这里给出下次发版可直接复用的摘要。
纯内部改动写「无」。
-->

## 发版声明

按 `AGENTS.md`：合并 PR 不等于获准发版。

- [ ] 本 PR 不含版本号、更新清单、tag 或 Release 资产变更
- [ ] 本 PR 是发版 PR（标题 `release: ...`），已同步版本号、`docs/releases/` 与 `app_update*.json`

## 截图 / 录屏

<!-- UI 改动请附改动前后对比；纯逻辑改动可删掉本节。 -->

## 检查清单

- [ ] 没有提交 `exports/`、`release/`、`node_modules/`、日志、本机绝对路径或临时探测脚本
- [ ] 新增逻辑有对应测试（`tests/` 或 `frontend/tests/`），或说明了不测的原因
- [ ] 错误文案是可直接展示给用户的中文，没有裸异常或英文堆栈
- [ ] 改动与现有代码风格一致，没有残留调试输出与死代码
