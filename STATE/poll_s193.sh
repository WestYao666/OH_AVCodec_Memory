#!/bin/bash
# S193 Approval Polling Script
# Checks pending_actions.yaml every 5 minutes for S193 decision

WORKSPACE="/home/west/.openclaw/workspace-main/avcodec-dfx-memory"
MEM_ID="MEM-ARCH-AVCODEC-S193"
DRAFT_FILE="$WORKSPACE/DRAFTS/MEM-ARCH-AVCODEC-S193.md"
MEMORY_FILE="$WORKSPACE/MEMORY/10_architecture/MEM-ARCH-AVCODEC-S193.md"
MAX_ATTEMPTS=12  # 12 * 5min = 60 minutes

echo "[$(date)] S193 polling script started"

for i in $(seq 1 $MAX_ATTEMPTS); do
    echo "[$(date)] Check $i/$MAX_ATTEMPTS"
    
    # Extract S193 decision from pending_actions.yaml
    DECISION=$(awk -v mem="$MEM_ID" '
        /^- type: approval_request/ { in_block=1; found=0 }
        in_block && /mem_id: MEM-ARCH-AVCODEC-S193/ { found=1 }
        found && /^  decision:/ { print $2; exit }
    ' "$WORKSPACE/STATE/pending_actions.yaml")
    
    echo "[$(date)] S193 decision: $DECISION"
    
    if [ "$DECISION" = "approve" ]; then
        echo "[$(date)] S193 APPROVED! Moving to MEMORY/"
        
        # Move draft to MEMORY if not already there
        if [ ! -f "$MEMORY_FILE" ]; then
            cp "$DRAFT_FILE" "$MEMORY_FILE"
            echo "[$(date)] Copied draft to MEMORY/"
        fi
        
        # Update status in file
        sed -i 's/\*\*状态\*\*/\*\*状态\*\*/; s/draft → pending_approval/approved ✓/; s/pending_approval/approved/g' "$MEMORY_FILE"
        
        # Add approved_at timestamp
        APPROVED_AT=$(date +%Y-%m-%dT%H:%M:%S%z)
        sed -i "s/\*\*生成时间\*\*/\*\*approved_at\*\*: $APPROVED_AT\n**生成时间\*\*/" "$MEMORY_FILE"
        
        # Git commit
        cd "$WORKSPACE"
        git add MEMORY/10_architecture/MEM-ARCH-AVCODEC-S193.md
        git commit -m "S193 approved: FFmpeg Audio Encoder Plugin体系——FFmpegBaseEncoder基类五子插件架构"
        git push origin master
        echo "[$(date)] Git commit+push done"
        
        # Update pending_actions.yaml decision
        awk -v mem="$MEM_ID" '
            /^- type: approval_request/ { in_block=1; found=0 }
            in_block && /mem_id: '"$MEM_ID"'/ { found=1 }
            found && /^  decision:/ { 
                print "  decision: approved"
                next
            }
            { print }
        ' "$WORKSPACE/STATE/pending_actions.yaml" > /tmp/pending_actions_new.yaml
        mv /tmp/pending_actions_new.yaml "$WORKSPACE/STATE/pending_actions.yaml"
        git add STATE/pending_actions.yaml
        git commit -m "S193 decision: approved"
        git push origin master
        
        echo "[$(date)] S193 APPROVAL COMPLETE!"
        exit 0
        
    elif [ "$DECISION" = "reject" ] || [ "$DECISION" = "revise" ]; then
        echo "[$(date)] S193 $DECISION - updating status and committing"
        
        # Update file status
        sed -i 's/draft → pending_approval/rejected (need revise)/g' "$DRAFT_FILE"
        
        # Git commit
        cd "$WORKSPACE"
        git add DRAFTS/MEM-ARCH-AVCODEC-S193.md STATE/pending_actions.yaml
        git commit -m "S193 $DECISION: updating draft status"
        git push origin master
        
        # Update pending_actions.yaml
        awk -v mem="$MEM_ID" -v dec="$DECISION" '
            /^- type: approval_request/ { in_block=1; found=0 }
            in_block && /mem_id: '"$MEM_ID"'/ { found=1 }
            found && /^  decision:/ { 
                print "  decision: '"$DECISION"'"
                next
            }
            { print }
        ' "$WORKSPACE/STATE/pending_actions.yaml" > /tmp/pending_actions_new.yaml
        mv /tmp/pending_actions_new.yaml "$WORKSPACE/STATE/pending_actions.yaml"
        git add STATE/pending_actions.yaml
        git commit -m "S193 decision: $DECISION"
        git push origin master
        
        echo "[$(date)] S193 $DECISION processed"
        exit 0
        
    else
        echo "[$(date)] No decision yet, waiting 5 minutes..."
        sleep 300  # 5 minutes
    fi
done

echo "[$(date)] Max polling attempts reached ($MAX_ATTEMPTS), exiting"
echo "[$(date)] S193 still pending, will be picked up by next run"
exit 1