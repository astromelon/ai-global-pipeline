"""Node 4 승인 게이트 — Antigravity CLI(agy) PreToolUse 훅.

agy의 --dangerously-skip-permissions 는 settings.json 의 ask 규칙과 훅의 force_ask 를 무시하므로,
원격 반영·이력 변경·삭제 명령은 이 훅에서 deny 로 막는다.
검사 대상은 도구 호출 인자(toolCall.args)의 문자열 값뿐이다(lastUserInput 등 대화 텍스트는 오탐 원인).
판정 실패(파싱 오류 등) 시에는 아무것도 출력하지 않고 통과시킨다.

게이트에 걸린 판정만 같은 폴더의 node4-approval-gate-agy.log(JSONL)에 남긴다.
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


LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node4-approval-gate-agy.log")
LOG_MAX_BYTES = 1_000_000
COMMAND_MAX_CHARS = 300

# 로그에 남기기 전에 가릴 자격증명 형태 (Claude 훅 ~/.claude/hooks/node4-approval-gate.py 와 동일)
REDACTIONS = [
    (re.compile(r"(://)[^/\s:@]+(?::[^/\s@]*)?@"), r"\1***@"),  # https://user:pass@host
    (re.compile(r"\b(glpat|ghp|gho|github_pat|sk|xox[abp])[-_][A-Za-z0-9_\-]{8,}"), r"\1-***"),
    (re.compile(r"(?i)(--?(?:token|password|passwd|secret|api[-_]?key)[=\s]+)\S+"), r"\1***"),
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_KEY)[A-Z0-9_]*=)\S+"), r"\1***"),
]


def strings(node):
    """JSON 트리의 모든 문자열 값을 모은다."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from strings(value)


# 명령 실행 도구의 명령 인자 이름. 파일 쓰기 본문(CodeContent 등)·검색어·경로 인자는 판정하지 않는다
# (README에 적은 'git push' 문구나 스크립트 속 'rm -rf' 가 오탐으로 거부되던 문제).
# 한계: 실제 agy 도구의 인자 이름은 확인하지 못했다. 이 목록에 없는 이름으로 명령을 받는 도구는 통과된다.
# 새 이름을 발견하면 여기에 추가하고, 게이트 로그(gate_report.py)로 확인한다.
COMMAND_KEYS = ("CommandLine", "commandLine", "command", "Command", "cmd", "Cmd", "script", "Script")


def command_texts(args) -> list:
    """도구 인자에서 명령 문자열만 모은다(문자열 또는 문자열 배열)."""
    found = []
    if isinstance(args, dict):
        for key in COMMAND_KEYS:
            value = args.get(key)
            if isinstance(value, str):
                found.append(value)
            elif isinstance(value, list):
                found.append(" ".join(str(part) for part in value))
    return found


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
    tool_call = data.get("toolCall") or {}
    args = tool_call.get("args") or {}
    commands = command_texts(args)
    hits = sorted({label for text in commands for label in gate_hits(text)})
    if not hits:
        return
    decision = "deny"
    command = " ; ".join(commands)
    write_log({
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "conversation_id": data.get("conversationId"),
        "step_idx": data.get("stepIdx"),
        "model": data.get("modelName"),
        "tool": tool_call.get("name"),
        "workspace": data.get("workspacePaths"),
        "hits": hits,
        "decision": decision,
        "command": redact(command),
    })
    emit(decision, "[Node 4 승인 게이트] " + ", ".join(hits)
         + " 명령은 사용자 승인(Node 4 질문에 대한 새 메시지의 Y)이 필요합니다.")


def emit(decision: str, reason: str) -> None:
    print(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=True))


# 훅 자체가 오류를 내면 원래는 명령이 그대로 통과한다(fail-open). 이 훅은 모든 도구 호출에 걸리므로 무조건 막지 않고,
# 도구 인자에 게이트 관련 단어가 보일 때만 거부한다(훅 버그 하나로 agy 전체가 멈추지 않게).
FALLBACK_WORDS = re.compile(r"(?i)\b(?:push|merge|rebase|reset|clean|branch|checkout|restore|stash|switch|glab|gh|rm"
                            r"|Remove-Item|del|rmdir|rd|erase|ri|Delete|Start-Process)\b")


if __name__ == "__main__":
    raw = ""
    try:
        raw = sys.stdin.read()
        main(raw)
    except Exception as error:
        try:
            scope = json.dumps((json.loads(raw).get("toolCall") or {}).get("args") or {}, ensure_ascii=False)
        except Exception:
            scope = raw  # 입력 자체를 해석할 수 없으면 전체를 본다
        if FALLBACK_WORDS.search(scope):
            write_log({"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                       "decision": "deny (hook error)", "error": type(error).__name__, "command": redact(scope)})
            emit("deny", "[Node 4 승인 게이트] 게이트 훅 오류(" + type(error).__name__ + ")로 명령을 판정하지 못해 "
                         "거부했습니다. 게이트 대상이 아니면 사용자에게 알리고 지시를 받으세요.")
