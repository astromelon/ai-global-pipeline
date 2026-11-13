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

# ==== 판정 공통 블록 시작 (세 훅 공통: Claude·agy·Codex — 글자 그대로 같아야 한다. test_gate_hooks_in_sync.py 가 비교) ====
# 판정 시간이 훅 timeout 을 넘으면 판정 없이 통과(fail-open)하므로, 반복자는 모두 상한을 둔다
# (OPT 는 16회, 문장 안 앞보기는 1000자). 상한을 넘는 비현실적 명령은 놓칠 수 있다.
OPT = r"(?:-\S+(?:\s+[^-\s]\S*)?(?:\s*\"\")?\s+){0,16}"  # git 전역 옵션(-C 경로, -c a=b, -c k="", --no-pager 등)
GIT = r"\bgit(?:\.exe|\.cmd)?\s+" + OPT
# 짧은 옵션 묶음(-qf)과 git 이 받아 주는 긴 옵션 약어(--h, --fo, --di)도 잡는다. 모호한 약어(--for)도 넓게 잡는다.
GATED = [
    (GIT + r"push(?![-\w])", "git push"),
    (GIT + r"merge(?![-\w])", "git merge"),
    (GIT + r"rebase(?![-\w])", "git rebase"),
    (GIT + r"reset(?![-\w])[^;&|\n]{0,1000}\s--h(?!elp\b)[\w-]*", "git reset --hard"),
    (GIT + r"clean(?![-\w])", "git clean"),
    (GIT + r"branch(?![-\w])(?:(?=[^;&|\n]{0,1000}\s-[a-zA-Z]*D)"
                              r"|(?=[^;&|\n]{0,1000}\s(?:-[a-zA-Z]*d|--de)[\w-]*(?![\w-]))"
                              r"(?=[^;&|\n]{0,1000}\s(?:-[a-zA-Z]*f|--fo)[\w-]*(?![\w-])))", "git branch -D"),
    (GIT + r"checkout(?![-\w])(?:(?=[^;&|\n]{0,1000}(?:\s--(?=\s|$)|\s\.(?=\s|$)|\s(?:-[a-zA-Z]*f|--f)[\w-]*(?![\w-])))"
                                r"|(?![^;&|\n]{0,1000}\s(?:-[bBtd](?![\w-])|--(?:orphan|track|no-track|detach)\b))"
                                r"(?=(?:\s+-\S+){0,16}\s+(?![0-9]*[<>])[^-\s;&|]\S*\s+(?![0-9]*[<>])[^-\s;&|]\S*))",
     "git checkout --"),
    (GIT + r"restore(?![-\w])(?:(?![^;&|\n]{0,1000}(?:--staged|\s-S\b))"
                               r"|(?=[^;&|\n]{0,1000}\s(?:--w[\w-]*|-[a-zA-Z]*W)))", "git restore"),
    (GIT + r"stash\s+(?:drop|clear)\b", "git stash drop/clear"),
    (GIT + r"switch(?![-\w])(?=[^;&|\n]{0,1000}\s(?:--di|--fo|-[a-zA-Z]*f)[\w-]*(?![\w-]))", "git switch --discard-changes"),
    (r"\bglab(?:\.exe)?\s+mr\b", "glab mr"),
    (r"(?i)\bglab(?:\.exe)?\s+api\b(?=[^;&|\n]{0,1000}(?:-X|--method)\s*=?\s*(?:PUT|POST|PATCH|DELETE)\b)", "glab api 쓰기"),
    (r"\bgh(?:\.exe)?\s+pr\s+merge\b", "gh pr merge"),
    (r"(?:^|[\s;&|({`/\\])(?<!docker )(?<!git )(?<!echo )rm(?:\.exe)?(?=\s|$|[;&|)}`])", "rm"),
    (r"(?i)\bRemove-Item\b", "Remove-Item"),
    (r"(?i)(?:^|[\s;&|({`])(?:del|rmdir|rd|erase|ri)(?:\s|/[sqfpa?](?=[\s/]|$)|[;&|)}`])", "del/rmdir"),
    (r"(?i)\[(?:System\.)?IO\.(?:File|Directory)\]::Delete\b", ".NET Delete"),
    (r"(?i)\bStart-Process\b(?:\s+-FilePath)?\s+git(?:\.exe)?\b", "Start-Process git"),
]

# ---- 따옴표·이스케이프 처리 ----
# 명령을 bash 규칙과 PowerShell(pwsh) 규칙으로 각각 토큰으로 나눈 뒤, 따옴표 안 문자열(커밋 메시지·echo·코드 리터럴)은
# 판정에서 뺀다. 단 셸에 넘기는 문자열(bash -c, pwsh -Command, cmd /c, iex, ssh, | bash, bash <<<, heredoc),
# $( ) 가 든 확장 문자열, 따옴표로 감싼 실행 파일 이름과 git/glab/gh 인자는 남긴다.
# 닫히지 않은 따옴표·heredoc 과 주석(#)은 원문 그대로 둔다(판정 누락보다 오탐이 안전하다).
JUDGE_MAX_CHARS = 100_000  # 이보다 긴 명령은 판정하지 않고 게이트에 건다(판정 시간 상한)
OVERSIZE_LABEL = "명령 길이 초과"
CONTEXT_MAX_CHARS = 200  # 명령 위치 판단에 쓰는 직전 문맥 길이
NEST_MAX_DEPTH = 4  # 셸 전달 문자열을 다시 풀어 보는 최대 깊이(넘으면 원문 유지)
SHELL_MODES = ("bash", "pwsh")
QUOTED_ARG_TOOLS = ("git", "glab", "gh")  # 따옴표 인자를 펼친 문자열(두 번째 결과)로도 판정하는 라벨의 첫 단어

SHELL_WORD = re.compile(r"(?i)(?<![\w.-])(?:(bash|sh|zsh|dash|wsl|ssh|eval)|(pwsh|powershell|iex|invoke-expression)|cmd)"
                        r"(?:\.exe)?(?![\w.-])")
PIPE_TO_SHELL = re.compile(r"(?i)\s*(?:sudo\s+)?(?:bash|sh|zsh|dash|pwsh|powershell|cmd|iex|invoke-expression)"
                           r"(?:\.exe)?(?![\w.-])")
QUOTED_TOOL = re.compile(r"(?i)(?:^|[\\/])(git|glab|gh)(?:\.exe|\.cmd)?$")
QUOTED_EXE = re.compile(r"(?i)(?:^|[\\/])(git|glab|gh|rm|del|rmdir|rd|erase|ri|Remove-Item)(?:\.exe|\.cmd)?$")
SIMPLE_WORD = re.compile(r"[A-Za-z][\w.-]*")
COMMAND_POSITION = re.compile(r"(?:^|[;&|{`]|(?<!@)\(|(?<![\w.-])(?:sudo|xargs|exec|call|start|env|command|nohup|time))"
                              r"\s*(?:[A-Za-z_]\w*=\S*\s+)*&?\s*$")  # @( 는 배열이라 제외. FOO=1 "rm" 도 명령 위치
QUOTED_ARG_CONTEXT = re.compile(r"(?i)(?<!Start-Process )(?<!-FilePath )\b(?:git|glab|gh)(?:\.exe|\.cmd)?\s")
HEREDOC = re.compile(r"<<(-?)[ \t]*(?:'([^'\n]*)'|\"([^\"\n]*)\"|\\?([\w.-]+))(?=[\s;&|<>()]|$)")
HERESTRING = re.compile(r"@([\"'])[ \t]*\r?\n")
SPECIAL = {"bash": re.compile(r"[\"'\\#<\n;&|]"), "pwsh": re.compile(r"[\"'`#@<\n;&|]")}
COMMENT_START = " \t\r\n;&|(){}"  # 이 문자 뒤(또는 맨 앞)의 # 부터 줄 끝까지가 주석


def tokenize(command: str, mode: str) -> list:
    """command 를 mode("bash"|"pwsh") 셸 규칙으로 (종류, 값) 토큰 목록으로 나눈다.

    종류: text(따옴표 밖 글자, 이스케이프 해제됨), sep(; & | 줄바꿈), raw(주석·닫히지 않은 나머지, 원문),
    dq(큰따옴표·@"..."@ 내용), sq(작은따옴표·@'...'@ 내용), hd(따옴표 없는 heredoc 본문), hdq(따옴표 heredoc 본문).
    heredoc 은 bash 모드에서만 인식한다.
    """
    tokens = []
    i, n = 0, len(command)
    special = SPECIAL[mode]
    jump_at, jump_to, body_from = -1, -1, -1  # heredoc 이 있는 줄의 끝 → 본문·종료 줄 다음으로 건너뛴다
    while i < n:
        m = special.search(command, i)
        stop = m.start() if m else n
        if stop > i:
            tokens.append(("text", command[i:stop]))
            i = stop
            continue
        c = command[i]
        if c == "\n" and i == jump_at:
            tokens.append(("sep", "\n"))
            i, jump_at, jump_to, body_from = jump_to, -1, -1, -1
            continue
        if c in ";&|\n":
            tokens.append(("sep", c))
            i += 1
            continue
        if c == "#":
            if i == 0 or command[i - 1] in COMMENT_START:
                end = command.find("\n", i)
                end = n if end < 0 else end
                tokens.append(("raw", command[i:end]))
                i = end
            else:
                tokens.append(("text", c))
                i += 1
            continue
        if (mode == "bash" and c == "\\") or (mode == "pwsh" and c == "`"):  # 따옴표 밖 이스케이프
            if i + 1 >= n:
                tokens.append(("text", c))
                i += 1
            elif command[i + 1] == "\n":  # 줄 이음
                i += 2
            else:
                tokens.append(("text", command[i + 1]))
                i += 2
            continue
        if c == "<":
            h = HEREDOC.match(command, i) if mode == "bash" else None
            line_start = command.rfind("\n", 0, i) + 1
            if h and (i == 0 or command[i - 1] != "<") and command.rfind("((", line_start, i) <= command.rfind("))", line_start, i):
                word = next(g for g in h.groups()[1:] if g is not None)
                line_end = command.find("\n", h.end()) if jump_at < 0 else jump_at
                if line_end >= 0:
                    start = line_end + 1 if body_from < 0 else body_from
                    term = re.compile(r"^" + (r"\t*" if h.group(1) else "") + re.escape(word) + r"\r?$", re.M)
                    t = term.search(command, start)
                    if not t:  # 닫히지 않은 heredoc: 나머지를 원문 그대로 둔다
                        tokens.append(("raw", command[i:]))
                        break
                    tokens.append(("text", "<<"))
                    tokens.append(("hd" if h.group(4) is not None else "hdq", command[start:t.start()]))
                    nl = command.find("\n", t.end())
                    jump_at, jump_to = line_end, (n if nl < 0 else nl)
                    body_from = jump_to + 1
                    i = h.end()
                    continue
            tokens.append(("text", c))
            i += 1
            continue
        if c == "@":  # pwsh here-string @"...\n"@ / @'...\n'@
            h = HERESTRING.match(command, i)
            close = command.find("\n" + h.group(1) + "@", h.end() - 1) if h else -1
            if close >= 0:
                body = command[h.end():close].rstrip("\r") if close >= h.end() else ""
                tokens.append(("dq" if h.group(1) == '"' else "sq", body))
                i = close + 3
                continue
            tokens.append(("text", c))
            i += 1
            continue
        j, buf, closed = i + 1, [], False  # 여기서 c 는 따옴표
        while j < n:
            d = command[j]
            if c == "'":
                if d == "'":
                    if mode == "pwsh" and j + 1 < n and command[j + 1] == "'":  # pwsh '' = '
                        buf.append("'")
                        j += 2
                        continue
                    closed = True
                    break
                buf.append(d)
                j += 1
                continue
            if mode == "bash" and d == "\\" and j + 1 < n and command[j + 1] in "\\\"$`\n":
                if command[j + 1] != "\n":
                    buf.append(command[j + 1])
                j += 2
                continue
            if mode == "pwsh" and d == "`" and j + 1 < n:
                buf.append(command[j + 1])
                j += 2
                continue
            if d == '"':
                if mode == "pwsh" and j + 1 < n and command[j + 1] == '"':  # pwsh "" = "
                    buf.append('"')
                    j += 2
                    continue
                closed = True
                break
            buf.append(d)
            j += 1
        if not closed:  # 닫히지 않은 따옴표: 원문 그대로 둔다
            tokens.append(("raw", command[i:]))
            break
        tokens.append(("dq" if c == '"' else "sq", "".join(buf)))
        i = j + 1
    return tokens


def neutralize_quotes(command: str, shell: str = "bash", depth: int = 0) -> tuple:
    """판정용 문자열 두 개(main, quoted_args)를 돌려준다.

    main: 따옴표 안 단순 문자열을 '""' 로 비운 것(모든 라벨 판정용).
    quoted_args: main 과 같되 git/glab/gh 문장의 공백 없는 따옴표 인자를 펼친 것(git·glab·gh 라벨 판정용).
    """
    tokens = tokenize(command, shell)
    piped = [False] * len(tokens)  # 같은 문장 안 뒤쪽에 '| bash' 같은 셸 파이프가 있는가
    flag = False
    for k in range(len(tokens) - 1, -1, -1):
        kind, value = tokens[k]
        piped[k] = flag
        if kind == "sep":
            if value != "|":
                flag = False
            elif k + 1 < len(tokens) and tokens[k + 1][0] == "text" and PIPE_TO_SHELL.match(tokens[k + 1][1]):
                flag = True
    out, alt = [], []
    tail, stmt_shell, stmt_git = "", None, False  # 현재 문장의 직전 문맥, 셸 이름(마지막), git/glab/gh 문장 여부
    for k, (kind, value) in enumerate(tokens):
        if kind == "sep":
            out.append(value)
            alt.append(value)
            tail, stmt_shell, stmt_git = "", None, False
            continue
        if kind in ("text", "raw"):
            main = second = value
        else:
            nxt = tokens[k + 1] if k + 1 < len(tokens) else None
            prev_ch = tail[-1:]
            next_ch = nxt[1][:1] if nxt is not None and nxt[0] == "text" else ""
            adjacent = kind in ("dq", "sq") and any(
                ch and not ch.isspace() and ch not in ";&|(){}" for ch in (prev_ch, next_ch)
            )
            expandable = kind in ("dq", "hd") and ("$(" in value or (shell == "bash" and "`" in value))
            stripped = value.strip()
            tool = QUOTED_TOOL.search(stripped)
            if stmt_shell is not None or piped[k] or expandable:  # 셸에 넘기는 문자열: 다시 풀어 판정
                if depth >= NEST_MAX_DEPTH:
                    main = second = " " + value + " "
                else:
                    inner = stmt_shell if stmt_shell in SHELL_MODES and not expandable else shell
                    a, b = neutralize_quotes(value, inner, depth + 1)
                    if "\\n" in value or "\\t" in value:
                        a2, b2 = neutralize_quotes(value.replace("\\n", "\n").replace("\\t", " "), inner, depth + 1)
                        a, b = a + " ; " + a2, b + " ; " + b2
                    main, second = " " + a + " ", " " + b + " "
            elif tool:  # "C:\...\git.exe" push
                main = second = " " + tool.group(1) + " "
            elif adjacent and re.fullmatch(r"[\w.-]*", value):  # git pu""sh, git reset --"hard", r"m"
                main = second = value
            elif stripped and (not re.search(r"\s", stripped) or QUOTED_EXE.search(stripped)) \
                    and COMMAND_POSITION.search(tail[-CONTEXT_MAX_CHARS:]):  # "rm" -rf, "/bin/rm", env "rm"
                main = second = " " + re.split(r"[\\/]", stripped)[-1] + " "
            else:  # 일반 문자열: 비운다. git/glab/gh 문장의 공백 없는 인자("--hard", "DELETE")는 second 에서 펼친다
                main = ' "" '
                second = " " + value + " " if stmt_git and value and not re.search(r"\s", value) else ' "" '
        out.append(main)
        alt.append(second)
        scan_from = max(0, len(tail) - 20)  # 새로 붙인 부분(과 경계 20자)만 검사해 전체 시간을 선형으로 유지
        tail += main
        for m in SHELL_WORD.finditer(tail, scan_from):
            stmt_shell = "bash" if m.group(1) else "pwsh" if m.group(2) else "same"
        if not stmt_git and QUOTED_ARG_CONTEXT.search(tail, scan_from):
            stmt_git = True
        if len(tail) > 2 * CONTEXT_MAX_CHARS:
            tail = tail[-CONTEXT_MAX_CHARS:]
    return "".join(out), "".join(alt)


def gate_hits(command: str, shell: str = None) -> list:
    """명령이 걸리는 게이트 항목을 GATED 순서대로 돌려준다.

    shell 이 "bash"/"pwsh" 면 그 셸 규칙으로만, 그 밖(None)이면 두 규칙 결과의 합집합으로 판정한다.
    """
    if len(command) > JUDGE_MAX_CHARS:
        return [OVERSIZE_LABEL]
    modes = (shell,) if shell in SHELL_MODES else SHELL_MODES
    mains, quoted = set(), set()
    for mode in modes:
        main, quoted_args = neutralize_quotes(command, mode)
        mains.add(main)
        quoted.add(quoted_args)
    quoted -= mains  # 같은 문자열은 한 번만 검사한다
    found = []
    for pattern, label in GATED:
        texts = mains | quoted if label.split()[0] in QUOTED_ARG_TOOLS else mains
        if any(re.search(pattern, text) for text in texts):
            found.append(label)
    return found
# ==== 판정 공통 블록 끝 ====


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
