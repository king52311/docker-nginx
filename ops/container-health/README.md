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

Docker 原生健康检查每 30 秒执行，超时 10 秒，3 次失败标记 unhealthy；它不会自动重启不健康容器或发送通知。正常重启保留检查；其他 Compose/Portainer **重新创建**容器会使用其自身配置，因此每次重新创建后需从本目录重新运行 `apply.py --apply`。部署单由本工具维护，不能把此前遗留的线上运行配置差异当作本次业务源码发布。

FindMe `.deploy/` 中入口/worker 容器 ID 是部署凭据。应用后必须根据经过健康验证的新容器更新对应 ID，镜像/提交标记保持。线上已有配置、证书和任务状态不覆盖，不触发业务镜像重建。
