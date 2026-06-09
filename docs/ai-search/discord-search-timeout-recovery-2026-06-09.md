# Discord Search Timeout Recovery

Date: 2026-06-09 KST  
Incident: Discord Search for `https://app.clickup.com/t/86ew25gkz` stopped after Codex timeout 600s; Claude fallback was unavailable because the Claude session limit had been reached. Side effects were 0.

## Root Cause

The failing message contained enough position text for a search:

- Physical AI / Robotics
- WMX Engine
- ROS2 package and node development
- NVIDIA Isaac Sim/Lab
- C/C++ embedded control
- Fleet management / hardware interest
- 전문연구요원 TO

The parser previously prioritized the ClickUp URL whenever a ClickUp URL was present. That meant a Discord message containing both a ClickUp URL and pasted JD text could still route as `clickup_url`, pushing the run toward ClickUp/engine execution instead of using the already-present JD. If the ClickUp path or long engine loop stalls, the user sees a 600s timeout even though a bounded search plan could have been returned immediately.

## Fix

Implemented in:

- `tools/multi_position_sourcing/request_parser.py`
- `tools/multi_position_sourcing/timeout_recovery.py`
- `tests/test_multi_position_sourcing.py`

New behavior:

1. If a Discord Search message contains a ClickUp/Wanted URL and pasted JD text, parse it as `url_plus_pasted_jd`.
2. Use the pasted JD immediately and treat the URL as a reference.
3. Build a bounded timeout-recovery artifact when Codex times out and Claude is unavailable.
4. For Physical AI/Robotics text, generate source-specific search keywords without profile-click automation or outreach.
5. Keep all side effects at zero until a later approved write step.

## Recovery Command

Save the Discord timeout report and latest user message into local files, then run:

```bash
python3 -m tools.multi_position_sourcing.timeout_recovery \
  --discord-report-file artifacts/discord_timeout_report_86ew25gkz.txt \
  --latest-message-file artifacts/discord_latest_message_86ew25gkz.txt \
  --local-artifact-glob 'artifacts/*ai_developer*shortlist*.json' \
  --local-artifact-glob 'artifacts/*ai_developer*longlist*.json' \
  --output artifacts/multi_position_sourcing/timeout-recovery-86ew25gkz.json
```

Expected artifact:

- `issue.codex_timed_out=true`
- `issue.codex_timeout_seconds=600`
- `issue.claude_session_limited=true`
- `routing_decision.input_kind=url_plus_pasted_jd`
- `routing_decision.use_discord_text_before_clickup_fetch=true`
- `search_plan.portal_keywords` includes ROS2 / Isaac Sim / C++ embedded / fleet queries
- `side_effects.*=0`

## Discord Bot Policy

When this condition is detected:

- Return a partial status by 90s.
- Stop the current Codex attempt by 180s unless it has already produced candidate evidence.
- Do not call Claude while the session-limit text is detected.
- Do not retry ClickUp fetch if the Discord message includes pasted JD text.
- Continue with local bounded search strategy and queue handoff.
- Never auto-click LinkedIn profiles, send InMail, write ClickUp, or save Supabase rows in timeout recovery.

Suggested operator response:

```text
Codex 600초 timeout과 Claude 세션 한도가 동시에 발생했습니다.
이번 메시지에는 JD 본문이 포함되어 있어 ClickUp 재조회 없이 Physical AI/Robotics 검색 계획으로 전환했습니다.
후보 저장/ClickUp/Supabase/제안 발송은 0건입니다.
```
