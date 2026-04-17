#!/bin/bash
# publish_after_approval.sh — 记忆工厂 Git 发布脚本
# 
# 用法：./publish_after_approval.sh <branch_name> <topic> <mem_file>
# 示例：./publish_after_approval.sh memory/update-20260417-avcodec-overview EVD-20260417-A1-001 EVIDENCE/code/avcodec_module_overview.yaml
#
# 流程：
#   1. 校验 mem 文件通过 validate_memory.py
#   2. 新建 branch（如果不存在）
#   3. 复制文件到目标 MEMORY/ 目录
#   4. 生成固定格式 commit
#   5. 推送到 origin
#   6. 输出发布结果

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="$HOME/.ssh/github_avcodec"
REMOTE="git@github.com:WestYao666/OH_AVCodec_Memory.git"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    echo "用法: $0 <branch_name> <topic> <mem_file>"
    echo "示例: $0 memory/update-20260417-avcodec-overview avcodec_module_overview EVIDENCE/code/avcodec_module_overview.yaml"
    exit 1
}

# 参数检查
[[ $# -ne 3 ]] && usage
BRANCH_NAME="$1"
TOPIC="$2"
MEM_FILE="$3"

cd "$REPO_DIR"

# 检查文件存在
if [[ ! -f "$MEM_FILE" ]]; then
    log_error "文件不存在: $MEM_FILE"
    exit 1
fi

# 校验
log_info "Running validate_memory.py ..."
if ! python3 SCRIPTS/validate_memory.py "$MEM_FILE"; then
    log_error "校验失败，文件不符合 memory entry 标准"
    exit 1
fi

# 判断目标路径
case "$MEM_FILE" in
    EVIDENCE/*)           TARGET_PATH="EVIDENCE/$(basename "$MEM_FILE")" ;;
    DRAFTS/proposals/*)  TARGET_PATH="MEMORY/$(basename "$MEM_FILE")" ;;
    MEMORY/*)             TARGET_PATH="$MEM_FILE" ;;
    *)                    TARGET_PATH="MEMORY/$(basename "$MEM_FILE")" ;;
esac

# 检查远程
log_info "Checking SSH connectivity to GitHub ..."
GIT_SSH_COMMAND="ssh -i $SSH_KEY" git ls-remote --heads "$REMOTE" &>/dev/null || {
    log_error "无法连接到 GitHub，请检查 SSH key 配置"
    exit 1
}

# 新建 branch
log_info "Creating branch: $BRANCH_NAME"
GIT_SSH_COMMAND="ssh -i $SSH_KEY" git checkout master 2>/dev/null || true
if GIT_SSH_COMMAND="ssh -i $SSH_KEY" git rev-parse --verify "$BRANCH_NAME" &>/dev/null; then
    log_warn "Branch already exists, checking out existing branch"
    GIT_SSH_COMMAND="ssh -i $SSH_KEY" git checkout "$BRANCH_NAME"
else
    GIT_SSH_COMMAND="ssh -i $SSH_KEY" git checkout -b "$BRANCH_NAME"
fi

# 复制文件
log_info "Copying $MEM_FILE -> $TARGET_PATH"
mkdir -p "$(dirname "$TARGET_PATH")"
cp "$MEM_FILE" "$TARGET_PATH"

# 生成 commit message
SHORT_SUM=$(python3 -c "
import yaml, sys
with open('$TARGET_PATH') as f:
    d = yaml.safe_load(f)
print(d.get('title', '$TOPIC')[:72])
" 2>/dev/null || echo "$TOPIC")

COMMIT_MSG="[MEM] $TOPIC - $SHORT_SUM"

# Commit
log_info "Committing ..."
GIT_SSH_COMMAND="ssh -i $SSH_KEY" git add "$TARGET_PATH"
GIT_SSH_COMMAND="ssh -i $SSH_KEY" git commit -m "$COMMIT_MSG"

# Push
log_info "Pushing to origin/$BRANCH_NAME ..."
GIT_SSH_COMMAND="ssh -i $SSH_KEY" git push -u origin "$BRANCH_NAME" 2>&1

log_info "Published successfully!"
log_info "Branch: $BRANCH_NAME"
log_info "File: $TARGET_PATH"
log_info "Commit: $(git rev-parse HEAD | cut -c1-8)"
