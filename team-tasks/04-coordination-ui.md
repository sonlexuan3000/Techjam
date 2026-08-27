# Task 04 — Coordination UI, Graph và Event Timeline

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-04-coordination-ui`
- **Reviewer:** `@sonlexuan3000`

## Mục tiêu

Thêm một Coordination view nhỏ vào React app hiện có để user chọn Planner,
Workers, nhập goal, launch một Coordination Run và quan sát graph/status/events.

Toàn bộ scheduling phải nằm ở backend. Frontend chỉ gửi command và poll một
coordination snapshot.

## Files sở hữu chính

```text
apps/web/src/coordination/CoordinationPanel.tsx
apps/web/src/coordination/CoordinationLaunchForm.tsx
apps/web/src/coordination/DagView.tsx
apps/web/src/coordination/EventTimeline.tsx
apps/web/src/types.ts
apps/web/src/api.ts
apps/web/src/styles.css
```

Chỉ sửa tối thiểu `apps/web/src/App.tsx` để thêm view switching. Trao đổi với
leader trước khi refactor phần single-Agent Playground.

## Launch form

- [ ] User goal/prompt textarea.
- [ ] Planner Agent dropdown.
- [ ] Worker Agent checklist.
- [ ] Hiển thị capability badges.
- [ ] Không cho chọn Agent `stopped` hoặc `busy` khi launch.
- [ ] Validate có một Planner và ít nhất hai Workers.
- [ ] Nút `Launch coordinated run`.
- [ ] Hiển thị API/validation error rõ ràng.

## Running view

- [ ] Poll một endpoint `GET /api/coordination-runs/:id`.
- [ ] Không poll từng AgentRun từ browser.
- [ ] Giữ polling sau khi task được retry.
- [ ] Dừng polling khi run terminal.
- [ ] Refresh browser vẫn mở lại được run gần nhất qua list endpoint.
- [ ] Hiển thị final output khi completed.

Mỗi task card cần có:

```text
Title
Dependencies
Required capability
Status
Assigned Agent
Attempt number
Output hoặc error có thể expand
```

Status colors:

```text
blocked    gray
ready      blue
running    purple
retrying   amber
completed  green
failed     red
```

## Graph scope

Không cần React Flow. Có thể render task cards theo topological level và hiển
thị dependency labels/arrows đơn giản. Mục tiêu là judge hiểu ordering, không
phải cung cấp graph editor.

## Event timeline

Hiển thị theo `sequence`, không chỉ timestamp:

```text
plan_requested
plan_validated
task_ready
attempt_started
attempt_timed_out
task_requeued
stale_result_rejected
task_completed
task_unblocked
coordination_completed
```

Event nên hiển thị task, attempt và Agent liên quan nếu có.

## Development không cần backend

Tạo một fixture snapshot local để code UI song song:

```text
planning
running với hai parallel tasks
retrying attempt 2
completed với final output
failed after max attempts
```

Xóa hoặc cô lập fixture khỏi production path trước khi merge.

## Verification

- [ ] TypeScript typecheck pass.
- [ ] Production build pass.
- [ ] Existing single-Agent UI vẫn hoạt động.
- [ ] Coordination UI không chứa scheduling logic.
- [ ] Empty/loading/error/terminal states đều dễ hiểu.
- [ ] Desktop hai cột graph/timeline.
- [ ] Mobile hoặc cửa sổ nhỏ vẫn sử dụng được theo một cột.

## Definition of Done

- Launch real Coordination Run qua API.
- Graph cập nhật khi task chuyển trạng thái.
- Retry và stale-result event nhìn thấy được.
- Không cần reload thủ công trong demo.
- `npm run check` pass.

## Ngoài scope

- Drag-and-drop graph editor.
- WebSocket/SSE.
- Adaptive-plan editing.
- Frontend gọi nhiều Worker API để tự orchestrate.
