"""Node 4 승인 게이트 — Claude Code PreToolUse 훅.

bypass 모드에서도 원격 반영·이력 변경·삭제 명령은 사용자 확인(ask)을 거치게 한다.
판정 실패(파싱 오류 등) 시에는 아무것도 출력하지 않고 통과시켜 일반 작업을 막지 않는다.

게이트에 걸린 판정만 같은 폴더의 node4-approval-gate.log(JSONL)에 남긴다.
확인창이 이 훅 때문인지 permissions.ask 규칙 때문인지 구분하는 근거로 쓴다.
로그에는 명령의 자격증명·토큰을 가린 뒤 앞부분만 기록하고, 1MB를 넘으면 .1로 회전한다.
로그 기록 실패는 판정에 영향을 주지 않는다.
"""
import datetime
import json
import os
import re
import sys

OPT = r"(?:-\S+(?:\s+[^-\s]\S*)?\s+)*"  # git 전역 옵션(-C 경로, -c a=b, --no-pager 등)
GIT = r"\bgit(?:\.exe)?\s+" + OPT
GATED = [
    (GIT + r"push(?![-\w])", "git push"),
    (GIT + r"merge(?![-\w])", "git merge"),
    (GIT + r"rebase(?![-\w])", "git rebase"),
    (GIT + r"reset\s+.*--hard\b", "git reset --hard"),
    (GIT + r"clean(?![-\w])", "git clean"),
    (GIT + r"branch(?![-\w])(?=[^;&|\n]*(?:\s-[a-zA-Z]*(?:D|d[a-zA-Z]*f|f[a-zA-Z]*d)[a-zA-Z]*(?=\s|$)"
                              r"|\s--delete\b[^;&|\n]*(?:--force\b|\s-f\b)|\s--force\b[^;&|\n]*--delete\b))", "git branch -D"),
    (GIT + r"checkout(?![-\w])(?:(?=[^;&|\n]*(?:\s--(?=\s|$)|\s\.(?=\s|$)|\s(?:-f|--force)\b))"
                                r"|(?![^;&|\n]*\s(?:-[bBtd](?![\w-])|--(?:orphan|track|no-track|detach)\b))"
                                r"(?=(?:\s+-\S+)*\s+(?![0-9]*[<>])[^-\s;&|]\S*\s+(?![0-9]*[<>])[^-\s;&|]\S*))", "git checkout --"),
    (GIT + r"restore(?![-\w])(?:(?![^;&|\n]*(?:--staged|\s-S\b))|(?=[^;&|\n]*(?:--worktree|\s-W\b)))", "git restore"),
    (GIT + r"stash\s+(?:drop|clear)\b", "git stash drop/clear"),
    (GIT + r"switch(?![-\w])(?=[^;&|\n]*(?:--discard-changes|\s(?:-f|--force)\b))", "git switch --discard-changes"),
    (r"\bglab\s+mr\b", "glab mr"),
    (r"(?i)\bglab\s+api\b(?=[^;&|\n]*(?:-X|--method)\s*=?\s*(?:PUT|POST|PATCH|DELETE)\b)", "glab api 쓰기"),
    (r"\bgh\s+pr\s+merge\b", "gh pr merge"),
    (r"(?:^|[\s;&|({`/\\])(?<!docker )(?<!git )(?<!echo )rm(?=\s|$|[;&|)}`])", "rm"),
    (r"(?i)\bRemove-Item\b", "Remove-Item"),
    (r"(?i)(?:^|[\s;&|({`])(?:del|rmdir|rd|erase|ri)(?:\s|/[sqfpa?](?=[\s/]|$)|[;&|)}`])", "del/rmdir"),
    (r"(?i)\[(?:System\.)?IO\.(?:File|Directory)\]::Delete\b", ".NET Delete"),
    (r"(?i)\bStart-Process\b(?:\s+-FilePath)?\s+git(?:\.exe)?\b", "Start-Process git"),
]

# ---- 따옴표 처리 (세 훅 공통: Claude·agy·Codex — ~/.ai-gate/test_gate_hooks_in_sync.py 로 동기화 검사) ----
# 따옴표 안 문자열(커밋 메시지·echo·코드 리터럴)은 판정에서 뺀다. 단, 셸에 넘기는 명령
# (cmd /c, pwsh -Command, bash -c, iex, eval, ssh 호스트)과 따옴표로 감싼 git/glab 실행 파일 경로는 남긴다.
# 닫히지 않은 따옴표는 지우지 않는다(판정 누락보다 오탐이 안전하다).
SHELL_PAYLOAD_PREFIX = re.compile(
    r"(?i)(?:\bcmd(?:\.exe)?(?:\s+/\w+)*\s+/[ck]"
    r"|\b(?:bash|sh|zsh|dash|pwsh|powershell|wsl)(?:\.exe)?\b(?:\s+\S+)*?\s+-{1,2}(?:[a-z]*c|command|commandwithargs|e|exec)"
    r"|\b(?:iex|invoke-expression|eval)"
    r"|\bssh(?:\.exe)?(?:\s+\S+)+)\s*$"
)
QUOTED_TOOL = re.compile(r"(?i)(?:^|[\\/])(git|glab)(?:\.exe|\.cmd)?$")
# 따옴표로 감싼 단순 단어는 명령 위치("rm" -rf)나 git 하위 명령 위치(git "push")에서, 또는 따옴표로 쪼갠 단어(git pu""sh)로
# 쓰일 때만 원문을 남긴다. 그 밖의 위치(echo "rm", -m "fix")는 문자열이므로 비운다.
SIMPLE_WORD = re.compile(r"[A-Za-z][\w.-]*")
COMMAND_POSITION = re.compile(r"(?:^|[;&|{`]|(?<!@)\(|\b(?:sudo|xargs|exec|call|start))\s*&?\s*$")  # @( 는 배열이라 제외
GIT_SUBCOMMAND = re.compile(r"(?i)(?<!Start-Process )(?<!-FilePath )\bgit(?:\.exe)?\s+" + OPT + r"$")  # Start-Process git 은 별도 항목


def neutralize_quotes(command: str) -> str:
    """판정용으로 따옴표 안 단순 문자열을 비운다(셸 명령·실행 파일 경로는 남긴다)."""
    out = []
    i, n = 0, len(command)
    while i < n:
        quote = command[i]
        if quote not in "\"'":
            out.append(quote)
            i += 1
            continue
        j, buf = i + 1, []
        while j < n:
            c = command[j]
            if quote == '"' and c in "\\`" and j + 1 < n and command[j + 1] == '"':
                buf.append('"')
                j += 2
                continue
            if c == quote:
                if quote == "'" and j + 1 < n and command[j + 1] == "'":
                    buf.append("'")
                    j += 2
                    continue
                break
            buf.append(c)
            j += 1
        if j >= n:  # 닫히지 않은 따옴표: 원문 그대로 둔다
            out.append(command[i:])
            break
        content = "".join(buf)
        tool = QUOTED_TOOL.search(content.strip())
        prev = "".join(out)
        adjacent = prev[-1:].isalnum() or command[j + 1:j + 2].isalnum()
        if SHELL_PAYLOAD_PREFIX.search(prev):
            out.append(" " + neutralize_quotes(content) + " ")
        elif tool:
            out.append(" " + tool.group(1) + " ")
        elif adjacent and (content == "" or SIMPLE_WORD.fullmatch(content)):
            out.append(content)  # git pu""sh, r"m" 처럼 따옴표로 쪼갠 단어는 이어 붙인다
        elif SIMPLE_WORD.fullmatch(content) and (COMMAND_POSITION.search(prev) or GIT_SUBCOMMAND.search(prev)):
            out.append(" " + content + " ")  # "rm" -rf, git "push"
        else:
            out.append(' "" ')
        i = j + 1
    return "".join(out)


def gate_hits(command: str) -> list:
    """명령이 걸리는 게이트 항목을 GATED 순서대로 돌려준다."""
    normalized = neutralize_quotes(command)
    return [label for pattern, label in GATED if re.search(pattern, normalized)]


LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node4-approval-gate.log")
LOG_MAX_BYTES = 1_000_000
COMMAND_MAX_CHARS = 300

# 로그에 남기기 전에 가릴 자격증명 형태
REDACTIONS = [
    (re.compile(r"(://)[^/\s:@]+(?::[^/\s@]*)?@"), r"\1***@"),  # https://user:pass@host
    (re.compile(r"\b(glpat|ghp|gho|github_pat|sk|xox[abp])[-_][A-Za-z0-9_\-]{8,}"), r"\1-***"),
    (re.compile(r"(?i)(--?(?:token|password|passwd|secret|api[-_]?key)[=\s]+)\S+"), r"\1***"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_KEY)[A-Z0-9_]*=)\S+"), r"\1***"),
]


def redact(command: str) -> str:
    """로그용으로 자격증명을 가리고 길이를 자른다."""
    for pattern, replacement in REDACTIONS:
        command = pattern.sub(replacement, command)
    if len(command) > COMMAND_MAX_CHARS:
        command = command[:COMMAND_MAX_CHARS] + "…"
    return command


def write_log(record: dict) -> None:
    """판정 한 건을 JSONL로 추가한다. 실패해도 예외를 밖으로 내보내지 않는다."""
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > LOG_MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        with open(LOG_PATH, "a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main(raw: str) -> None:
    data = json.loads(raw)  # 해석 실패는 아래 __main__ 의 오류 처리로 넘긴다
    command = (data.get("tool_input") or {}).get("command") or ""
    hits = gate_hits(command)
    if not hits:
        return
    decision = "ask"
    reason = (
        "[Node 4 승인 게이트] " + ", ".join(hits) + " 명령은 사용자 승인이 필요합니다. "
        "Node 4 질문에 사용자가 새 메시지로 Y라고 답한 경우에만 승인하세요."
    )
    write_log({
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_id": data.get("session_id"),
        "tool_use_id": data.get("tool_use_id"),
        "permission_mode": data.get("permission_mode"),
        "tool": data.get("tool_name"),
        "cwd": data.get("cwd"),
        "hits": hits,
        "decision": decision,
        "command": redact(command),
    })
    emit(decision, reason)


def emit(decision: str, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=True))


# 훅 자체가 오류를 내면 원래는 명령이 그대로 통과한다(fail-open). 입력에 게이트 관련 단어가 보이면 확인을 받는다.
FALLBACK_WORDS = re.compile(r"(?i)\b(?:push|merge|rebase|reset|clean|branch|checkout|restore|stash|switch|glab|gh|rm"
                            r"|Remove-Item|del|rmdir|rd|erase|ri|Delete|Start-Process)\b")


if __name__ == "__main__":
    raw = ""
    try:
        raw = sys.stdin.read()
        main(raw)
    except Exception as error:
        if FALLBACK_WORDS.search(raw):
            write_log({"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                       "decision": "ask (hook error)", "error": type(error).__name__, "command": redact(raw)})
            emit("ask", "[Node 4 승인 게이트] 게이트 훅 오류(" + type(error).__name__ + ")로 명령을 판정하지 못했습니다. "
                        "게이트 대상일 수 있으니 사용자 확인 후 진행하세요.")
