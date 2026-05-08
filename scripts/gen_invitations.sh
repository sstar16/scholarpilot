#!/bin/bash
# 生成 N 个一次性邀请码。需要 admin 账号的邮箱+密码。
#
# 用法:
#   ./scripts/gen_invitations.sh                    # 默认 20 个
#   ./scripts/gen_invitations.sh 5 "beta wave 2"     # 5 个 + 备注

set -e

COUNT="${1:-20}"
NOTE="${2:-内测邀请码}"
HOST="${HOST:-http://localhost:8000}"
EMAIL="${ADMIN_EMAIL:-}"

if [ -z "$EMAIL" ]; then
  read -rp "Admin email: " EMAIL
fi
read -rsp "Admin password: " PW
echo

echo "[1/2] 登录获取 token..."
TOKEN=$(curl -sS -X POST "$HOST/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\"}" \
  | python -c "import sys, json; d=json.load(sys.stdin); print(d.get('access_token') or '')")

if [ -z "$TOKEN" ]; then
  echo "登录失败，检查邮箱/密码" >&2
  exit 1
fi

echo "[2/2] 生成 $COUNT 个邀请码..."
curl -sS -X POST "$HOST/api/admin/invitations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"count\":$COUNT,\"note\":\"$NOTE\"}" \
  | python -c "
import sys, json
data = json.load(sys.stdin)
if isinstance(data, dict) and 'detail' in data:
    print(f'Error: {data[\"detail\"]}', file=sys.stderr); sys.exit(1)
print(f'{'Code':<20} {'Note':<30}')
print('-' * 55)
for c in data:
    print(f'{c[\"code\"]:<20} {c.get(\"note\") or \"\":<30}')
print()
print(f'Total: {len(data)} codes generated.')
"
