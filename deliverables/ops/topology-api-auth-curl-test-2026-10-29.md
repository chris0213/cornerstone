# Topology 接口鉴权 curl 测试手册

> 适用版本：`92b92fd`（topology 路由统一补 JWT 鉴权）
> 背景：`/api/v1/topology/*` 全部 15 个接口自该版本起要求登录（`Authorization: Bearer <token>`），未带 token 或 token 无效返回 `401`。
> 更新日期：2026-10-29

## 准备

- 后端地址默认 `http://localhost:8000`，生产环境替换 `BASE` 即可。
- `admin` 密码替换为实际值；或使用任意已启用账号。
- 需要本机有 `python3`（用于解析 token 与格式化 JSON，可换成 `jq`）。

## 1. 登录拿 token

```bash
BASE=http://localhost:8000

TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=你的密码" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

echo $TOKEN   # 确认拿到了 token
```

> token 有效期默认 30 分钟（refresh token 12 小时），过期后重新登录即可。

## 2. 带 token 调用 topology 接口（应返回 200）

```bash
# 站点拓扑图
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/site-graph" | python3 -m json.tool

# 设备拓扑图（可加 ?site_id=1）
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/device-graph" | python3 -m json.tool

# 设备连接关系列表（分页）
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/device-links?limit=10&skip=0" | python3 -m json.tool

# 单个连接关系（替换 <link_id>）
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/device-links/<link_id>" | python3 -m json.tool

# 站点设备列表
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/site-devices?site_id=1" | python3 -m json.tool

# 未知接入终端列表（可加 ?device_id=1 过滤）
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/unknown-endpoints" | python3 -m json.tool

# 发起 LLDP 发现（返回 task_id）
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/discover-lldp"

# 发起 MAC/ARP 发现
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/discover-mac"

# 轮询发现任务进度（替换 <task_id>）
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/discovery-tasks/<task_id>" | python3 -m json.tool
```

## 3. 验证鉴权生效（不带 token，应返回 401）

```bash
curl -s -o /dev/null -w "site-graph: %{http_code}\n"      "$BASE/api/v1/topology/site-graph"
curl -s -o /dev/null -w "discover-lldp: %{http_code}\n" -X POST "$BASE/api/v1/topology/discover-lldp"
curl -s -o /dev/null -w "token 错误: %{http_code}\n" -H "Authorization: Bearer wrong-token" "$BASE/api/v1/topology/site-graph"
```

## 4. 一条命令快速全量体检（打印各接口状态码）

```bash
for ep in "site-graph" "device-graph" "device-links" "unknown-endpoints" "site-devices?site_id=1"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/$ep")
  echo "$ep -> $code"
done
```

预期输出全部为 `200`；把 `-H "Authorization: ..."` 一行去掉再跑，应全部为 `401`。

## 5. 写操作示例（谨慎执行）

```bash
# 创建连接关系（source/target 至少各有一端；按实际 id 修改）
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"source_device_id": 1, "target_device_id": 2, "source_interface": "Gi0/1", "target_interface": "Gi0/2", "link_type": "manual", "confidence": 100}' \
  "$BASE/api/v1/topology/device-links"

# 更新连接关系（替换 <link_id>）
curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"source_interface": "Gi0/9"}' \
  "$BASE/api/v1/topology/device-links/<link_id>"

# 删除连接关系（替换 <link_id>）
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/device-links/<link_id>"

# 更新专线连接的设备（替换 <circuit_id>；断开连接传 connected_device_id 省略/置 null）
curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/topology/circuits/<circuit_id>/connect?connected_device_id=3"

# 忽略未知接入终端（替换 <endpoint_id>）
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/topology/unknown-endpoints/<endpoint_id>"

# 未知接入终端一键入库为服务器（替换 <endpoint_id>，name 必填）
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "app-server-01", "device_type": "server", "create_ip": true}' \
  "$BASE/api/v1/topology/unknown-endpoints/<endpoint_id>/accept"
```

## 6. 常见返回码

| 状态码 | 含义 | 排查 |
| --- | --- | --- |
| 200 | 正常 | — |
| 401 | 未带 token / token 无效或过期 | 重新登录拿 token；检查 `Authorization: Bearer ` 前缀与空格 |
| 400 | 参数校验失败（如无凭证、无管理 IP、连接关系重复） | 看 `detail` 文案 |
| 404 | 资源不存在（连接关系 / 专线 / 未知接入 / 任务 ID） | 任务 404 多为服务重启后内存任务丢失，重新发起发现 |
| 429/423 | 登录限流（IP 喷洒 / 用户名锁定） | 等 10~15 分钟或重启后端清内存计数 |

## 附：相关回归测试

```bash
cd backend && python -m pytest tests/test_discovery_task.py -q
```

覆盖：无 token 全接口 401、发现任务主事件循环运行、任务成功/失败状态机。
