# -*- coding: utf-8 -*-
"""verify.cmd에서 호출하는 라우팅 로직 자가 점검.

cmd.exe의 `-c "..."` 인자로 한글 리터럴을 넘기면 콘솔 코드페이지 때문에
깨질 수 있어(known-issues.md 8/9번과 같은 계열), 별도 .py 파일(UTF-8)로
분리했다. 실패하면 0이 아닌 코드로 종료한다.
"""
import sys

sys.path.insert(0, ".")

from voice.listener import SessionTable, route_command, parse_stop_command  # noqa: E402

# --- 세션이 하나뿐인 기본 케이스 (규칙 ④) ---
table = SessionTable()
table.upsert_from_notify("s1", "proj-x", "s1", "tok1")

routed = route_command(table, "anything")
assert routed is not None and routed.project_name == "proj-x"

assert parse_stop_command("멈춰") is None
assert parse_stop_command("멈춰 proj-x") == "proj-x"

# --- 다중 세션 라우팅 규칙 ①②③ + active 필터링
# (2026-09-26 밤모드: verify_routing.py 코드 리뷰 중 이 규칙들이 유닛테스트로만
# 수동 검증됐을 뿐 verify.cmd 상시 회귀 테스트엔 없던 걸 발견해 승격) ---
multi = SessionTable()
multi.upsert_from_notify("s1", "proj-a", "s1", "tok1")
multi.upsert_from_notify("s2", "proj-b", "s2", "tok2")

# 규칙 ①: 프로젝트명으로 시작하면 active 무관하게 그 세션 (즉시 재활성화)
hit = route_command(multi, "proj-b 다음 작업 해줘")
assert hit is not None and hit.project_name == "proj-b", "규칙 ① 실패"

# 규칙 ②: 프로젝트명 언급이 없으면 last_notify_at이 가장 최근인 active 세션
multi.upsert_from_notify("s1", "proj-a", "s1", "tok1")  # proj-a를 더 최근으로
hit2 = route_command(multi, "다음 작업 해줘")
assert hit2 is not None and hit2.project_name == "proj-a", "규칙 ② 실패"

# active 필터링: detach된 세션은 규칙 ②/③ 후보에서 제외되지만, 규칙 ①(프로젝트명
# 직접 호출)은 active 무관하게 항상 즉시 재활성화한다
multi.mark_detached("s1")
hit3 = route_command(multi, "다음 작업 해줘")  # proj-a는 detach됐으니 proj-b로
assert hit3 is not None and hit3.project_name == "proj-b", "detach 필터링 실패"
hit4 = route_command(multi, "proj-a 계속해줘")  # 직접 호출은 detach여도 즉시 재활성화
assert hit4 is not None and hit4.project_name == "proj-a", "규칙 ① 재활성화 실패"

print("routing checks OK")
