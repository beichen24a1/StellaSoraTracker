<script setup lang="ts">
import { useAppStore } from '../store'
const store = useAppStore()
</script>
<template>
  <section class="page help-page"><div class="page-heading"><div><h1>使用说明与风险提示</h1><p class="muted">面向《星塔旅人》Windows 客户端的非官方抽卡记录整理工具。</p></div></div><div class="panel help-content"><h2>使用方法</h2><ol><li>登录游戏进入主界面，依次打开各类招募记录（含周年特选），等待每个列表显示。</li><li>回到工具点击“抓取抽卡记录”。多开时选择具体游戏进程，等待结果自动显示。</li><li>在“招募记录”中按卡池、名称或记录类型筛选，完整记录支持分页浏览。</li><li>名称、头像与卡池信息会自动补全，也可在设置中手动同步。</li></ol><h2>数据与备份</h2><p>每个 UID 的主归档位于 <code>exports/&lt;UID&gt;.json</code>，独立账号配置和旧档继续保留。建议定期备份整个 <code>exports</code>。</p><p>导入前会备份目标归档；备份失败会停止导入。没有 UID 的旧档不会自动认领，归属不明或损坏时停止保存。</p><h2>上传与更新</h2><p>自动上传默认关闭。每次上传成功后仍需向蕾姆发送绑定指令确认。软件更新在下载前展示说明，校验后由你选择立即安装或稍后安装。</p><h2 class="risk-title">风险与免责声明</h2><ul><li>本工具与游戏运营方、开发方无关联，未经游戏官方认可或授权。</li><li>通过 ReadProcessMemory 只读访问已加载的招募历史；不注入、不修改游戏文件或内存、不发送游戏协议请求。</li><li>游戏更新可能改变数据结构或反作弊策略。请自行阅读服务条款、评估风险，并仅在获授权的账号和设备上使用。</li><li>导出不含账号密码、Cookie 或 SDK Token，但会反映游戏行为，请谨慎分享。</li><li>使用者自行承担使用后果。</li></ul><h2>来源与许可</h2><p>本项目整合自 sfjdk/StellaSoraTracker 与 zhenkotone/stellasora_gacha，保留原贡献者署名及提交历史；beichen24a1 负责整合协调与维护。</p><p>项目代码采用 MIT。游戏素材及第三方依赖保留各自权利与许可证，ZIP 中附带许可说明。</p><div class="help-version">星塔旅人数据工具 · v{{ store.state?.version }} · Windows</div></div></section>
</template>
