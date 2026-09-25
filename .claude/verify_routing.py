# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 라우팅 로직 자가 점검.

cmd.exe의 `-c "..."` 인자로 한글 리터럴을 넘기면 콘솔 코드페이지 때문에
깨질 수 있어(known-issues.md 8/9번과 같은 계열), 별도 .py 파일(UTF-8)로
분리했다. 실패하면 0이 아닌 코드로 종료한다.
"""
import sys

sys.path.insert(0, ".")

from voice.listener import SessionTable, route_command, parse_stop_command  # noqa: E402

table = SessionTable()
table.upsert_from_notify("s1", "proj-x", "s1", "tok1")

routed = route_command(table, "anything")
assert routed is not None and routed.project_name == "proj-x"

assert parse_stop_command("멈춰") is None
assert parse_stop_command("멈춰 proj-x") == "proj-x"

print("routing checks OK")
