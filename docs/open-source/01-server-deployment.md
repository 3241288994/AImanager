# 服务器安全部署

## 安全默认部署

需要 Docker Compose v2。复制示例环境文件并创建仅本机可读的首次启动密码：

```bash
cp deploy/.env.example deploy/.env
umask 077
openssl rand -base64 32 > deploy/.web-access-password
chmod 600 deploy/.web-access-password
```

编辑 `deploy/.env`，把 `CODEXMANAGER_WEB_ACCESS_PASSWORD_FILE_HOST` 设置为该密码文件的绝对路径。然后启动：

```bash
docker compose --env-file deploy/.env -f deploy/docker-compose.self-hosted.yml up -d --build
curl -fsS http://127.0.0.1:48761/__auth_status
```

该 Compose 默认具有以下边界：

- 仅把 Web 端口发布到 `127.0.0.1`；公网和局域网不能直接访问。
- 容器使用 UID/GID `10001`，移除 Linux capabilities，并启用 `no-new-privileges`。
- Service 的 `48760` 端口不发布到宿主机；Web 仅在容器网络中转发受认证保护的管理请求。
- 数据写入 Docker 命名卷；数据库、RPC token、账号信息和日志均不进入源码。
- 网关详细日志默认关闭，避免请求内容或身份线索进入容器日志。
- Web 密码通过 Docker secret 挂载，并在新数据卷首次启动时仅保存其哈希；不会写入 Compose、镜像或源码。

启动后访问 Web 控制台并使用密码文件中的值登录。若有意轮换密码，替换文件后将 `CODEXMANAGER_WEB_ACCESS_PASSWORD_RESET=1` 运行一次，再恢复为 `0`。完成认证验证前，不要配置公网反向代理。

## 从本地安全访问

在自己的电脑建立 SSH 转发：

```bash
ssh -N -L 48761:127.0.0.1:48761 your-user@your-server
```

然后访问 `http://127.0.0.1:48761/`，使用创建密码文件中的值登录。该公开版只提供受保护的
管理控制台；不提供 OpenAI 兼容 `/v1` 网关。

SSH 转发只解决管理者浏览器到服务器的访问问题；它不会把管理 RPC 或 LabContext
管理员接口变成可供模型调用的公共接口。

## 可选连接 LabContext

AImanager 只会连接 LabContext 的**管理员控制面**，不是模型工具 endpoint。原生运行时
默认地址为 `http://127.0.0.1:1455/admin`，可显式覆盖：

```bash
export LABCONTEXT_ADMIN_URL=http://127.0.0.1:1455/admin
export LABCTX_ADMIN_TOKEN_FILE="$HOME/.local/state/labcontext/admin.token"
```

将上述变量放入 systemd、launchd 或其他私有部署环境；不要写入 Git、Docker 镜像、浏览器
配置或公开 issue。

### Docker 与宿主机上的 LabContext

如果 LabContext 运行在同一台 Docker 宿主机，填入 `deploy/.env`：

```dotenv
LABCONTEXT_ADMIN_URL=http://host.docker.internal:1455/admin
LABCTX_ADMIN_TOKEN_FILE_HOST=/absolute/path/to/labcontext/admin.token
```

再附加只读 token 覆盖文件：

```bash
docker compose --env-file deploy/.env \
  -f deploy/docker-compose.self-hosted.yml \
  -f deploy/docker-compose.labcontext.example.yml \
  up -d --build
```

容器以 UID 10001 运行，因此 token 文件需要对该 UID 可读；使用所有者、组或 ACL 授权，
不要为了绕过权限而把 token 设为全局可读。覆盖文件仅允许
`host.docker.internal` 这一个 Docker 宿主机网关。服务端也会拒绝任意远程主机和 HTTPS
管理员 URL。

个人 SSH Host 别名和临时端口转发命令不应进入仓库配置。若
LabContext 只能通过转发访问，请让转发进程与原生 AImanager 在同一私有网络边界内运行，
或将 LabContext 部署到同一 Docker 宿主机；不要把管理员端口暴露到公网。

## 接口边界

| 边界 | 典型路径 | 是否应公开 |
| --- | --- | --- |
| Web 控制台 | `/` | 私有；经 SSH、VPN 或受控反代 |
| 管理 RPC | `/api/rpc`、`/rpc` | 不公开，不提供给模型 |
| OpenAI 兼容网关 | `/v1/responses` 等 | 当前公开版不暴露；不要作为客户端或 MCP 地址使用 |
| LabContext 管理端 | `127.0.0.1:1455/admin` | 不公开，仅控制面使用 |
| 可选 MCP Router | 本机 `127.0.0.1:1460/mcp` | 仅由 Secure MCP Tunnel 访问；不直接公开 |

可选 Router 与服务器部署解耦，并应运行在管理者自己的电脑上；它可以把 SSH 转发后的 server
Provider 与本机 local Provider 聚合为一个 MCP endpoint。安装和三种模式见
[统一 LabContext Router](../labcontext-router.md)。

若未来必须公网部署，至少增加 HTTPS、强认证、限流、请求体大小限制、审计日志脱敏，并把
管理域名与模型工具域名拆分。不要直接修改安全 Compose 的回环端口映射来“临时上线”。
