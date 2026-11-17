# PROJECT_HISTORY

- 2026-11-17：新增 ops/container-health，维护服务器 21 个容器的原生健康检查；静态探针适配无 shell 的 Portainer，逐个保留镜像/挂载/网络重建，失败恢复；备份私有化、同配置跳过、并发锁，3 项挂载/回退单测通过。待线上预检与应用。
