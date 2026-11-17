# CURRENT_CONTEXT

- 2026-11-17：新增 ops/container-health，维护服务器 21 个容器的原生健康检查；静态探针适配无 shell 的 Portainer，逐个保留镜像/挂载/网络重建，失败恢复；备份私有化、同配置跳过、并发锁，3 项挂载/回退单测通过。待线上预检与应用。

- 2026-11-17：预检核实外层 Nginx 仅监听 HTTPS，改为本机 SNI 域名请求；pgAdmin 使用镜像自带 Python 检查 /misc/ping，兼容其非 root 安全执行限制。其他探针预检通过。
