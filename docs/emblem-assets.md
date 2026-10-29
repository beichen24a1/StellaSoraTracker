# 纹章缩略图

九枚纹章图片来自用户指定的 [StellaBase 纹章页](https://stella.ennead.cc/emblems)，数据接口为 `https://stella.ennead.cc/api/emblems?lang=cn`。游戏素材权利归原权利人，不属于本项目 MIT 授权的代码范围。

原始 PNG 保存在 `assets/emblems/<StellaBase ID>.png`，随 Electron 包提供，离线可用；完整来源 URL 与 SHA-256 见 `frontend/src/emblems.json`。这里的 ID 是该站点的目录编号，不据此猜测游戏实例中的 `nGemId`。

界面优先用游戏中的 `sIcon` 路径精确匹配目录；旧缓存缺少图标路径时按完整名称匹配。未知纹章或图片读取失败时显示中性占位图，不借用别的纹章图片。列表及独立详情只展示缩略图和养成数据，隐藏背景描述；原始缓存字段保留。

更新素材：在开发环境执行 `./.venv/Scripts/python.exe tools/fetch_emblem_assets.py`。脚本校验 PNG 格式、路径与文件大小，重新生成映射和来源摘要。正常浏览页面不会向外部站点发送请求。
