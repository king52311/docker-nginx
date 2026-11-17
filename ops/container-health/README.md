# Docker 容器健康检查

维护本机 21 个容器的 Docker 原生 HEALTHCHECK。已经有检查的 API、MCP 和后台槽位保留原有配置，其余逐个补齐。

- HTTP：Nginx、网关、PHP、数据库管理页、Portainer；Portainer 的自签证书例外仅允许回环 HTTPS。
- 数据库：MySQL `mysqladmin ping`、PostgreSQL `pg_isready`、Redis PING 协议响应（认证开启时 NOAUTH 也证明服务响应，不保存凭证）。
- 任务：FindMe worker 检查准确的模块进程及数据库 SELECT 1；LarkCron 检查调度进程。它们反映进程/依赖可用性，不证明每项业务任务完成或事件循环无阻塞。
- 代理/旧 ASP：检查实际代理/监听端口；FastCGI 端口不能当 HTTP 检查。

## 安全部署

从 Git 提交编译 Linux 静态探针（标准库，无第三方依赖），并记录源码提交与产物 SHA256：

```sh
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GO111MODULE=off go build -trimpath -ldflags='-s -w' -o probe-linux-amd64 probe.go
python3 apply.py --binary /data/docker-health/releases/<commit>/probe-linux-amd64
python3 apply.py --binary /data/docker-health/releases/<commit>/probe-linux-amd64 --apply
```

默认只读计划，`--only <容器名...>` 可分批应用。只对运行中的容器操作。预检必须先验证所有探针能在当前镜像、网络、PID 命名空间工作，再应用。

工具保留当前不可变镜像 ID、挂载源（包括匿名卷）、端口、资源限制、环境变量、网络别名、静态地址与重启策略。健康探针通过只读运行产物挂载注入；应用配置来自已推送 Git。重建时短暂停止旧容器，失败恢复；单实例数据库与代理安排维护窗口。通过后移除旧容器。原始 inspect 包含凭据，只保存在服务器 `/data/docker-health/backups/`（0700/0600），绝不提交 Git 或打印。

Docker 原生健康检查每 30 秒执行，超时 10 秒，3 次失败标记 unhealthy；它不会自动重启不健康容器或发送通知。正常重启保留检查；FindMe 已在发布 Compose 直接保存网关/worker 检查，其余受管 Compose 项目新增 `docker-compose.override.yml`，默认重建自动保留；显式 `-f` 时须同时指定覆盖文件。Portainer 和原始部署目录已缺失的旧 ASP 容器由本工具管理，其手工重新创建后需重新运行 `apply.py --apply`。部署单由本工具维护，不能把此前遗留的线上运行配置差异当作本次业务源码发布。

FindMe `.deploy/` 中入口/worker 容器 ID 是部署凭据。应用后必须根据经过健康验证的新容器更新对应 ID，镜像/提交标记保持。线上已有配置、证书和任务状态不覆盖，不触发业务镜像重建。

## 已验收

2026-11-17：21/21 容器全部 running/healthy；17 项新增探针预检、3 项单元测试、真实 Docker 匿名卷保留/失败回退验证通过。17 个容器仅改健康配置，其不可变业务镜像 ID 和原挂载保留，原有 4 个健康容器保持。服务器 Nginx 的既有配置/证书差异已私有备份，未覆盖。验收 `/data/docker-health/acceptance-20261117.json`，私有回退记录 `/data/docker-health/backups/`。
