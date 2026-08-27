# Task 04 — Coordination UI, Graph và Event Timeline

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-04-coordination-ui`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

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
apps/web/src/coordination/polling.ts
apps/web/src/coordination/polling.test.ts
apps/web/src/types.ts
apps/web/src/api.ts
apps/web/src/styles.css
apps/web/package.json
package.json                         # chỉ nối web test vào root test script
package-lock.json                    # thay đổi do thêm web test dependency
```

Chỉ sửa tối thiểu `apps/web/src/App.tsx` để thêm view switching. Trao đổi với
leader trước khi refactor phần single-Agent Playground.

## Launch form

- [ ] Mở rộng existing create/settings Agent form bằng capabilities input và gửi
  optional `capabilities: string[]` qua existing Agent API.
- [ ] User goal/prompt textarea.
- [ ] Planner Agent dropdown.
- [ ] Worker Agent checklist.
- [ ] Hiển thị capability badges.
- [ ] Chỉ cho chọn Planner/Workers đang `ready`; Agent `busy`, `error` hoặc
  `stopped` không selectable.
- [ ] Validate có đúng một Planner, `2–8` unique Workers và Planner không nằm
  trong Worker IDs (backend vẫn validate lại).
- [ ] Nút `Launch coordinated run`.
- [ ] Hiển thị API/validation error rõ ràng.

## Running view

- [ ] Poll một endpoint `GET /api/coordination-runs/:id`.
- [ ] Không poll từng AgentRun từ browser.
- [ ] Giữ polling sau khi task được retry.
- [ ] Khi thấy run terminal, tiếp tục poll detail thêm một khoảng cố định ngắn
  `TERMINAL_EVENT_GRACE_MS = 10_000`. Deadline tính tuyệt đối từ snapshot terminal
  đầu tiên, không reset khi có event mới; poll tới deadline rồi dừng.
- [ ] Hủy timer/poll khi component unmount hoặc user chuyển sang run khác; response
  cũ không được ghi đè snapshot của run mới.
- [ ] Có nút Stop khi run `planning/running`; gọi đúng
  `POST /api/coordination-runs/:id/stop`, sau đó cũng dùng khoảng poll cuối như
  trên để task/attempt/event không còn cũ trên UI.
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
skipped    gray
cancelled  gray
```

`retrying` chỉ là derived label khi
`task.status === "ready" && task.attemptCount > 0`; nó không được thêm vào
`CoordinationTaskStatus` hoặc gửi về backend.

## Tương thích single-Agent Playground

- [ ] Nếu gửi message tới Agent đang được Coordination Run giữ và API trả `409`,
  hiển thị lỗi dễ hiểu, hướng dẫn stop việc nhóm trước.
- [ ] Giữ hoặc khôi phục nội dung prompt sau `409`; không để user phải gõ lại.
- [ ] Không append Message, không tạo active Run giả và không đổi Agent sang
  `busy` ở frontend khi request bị reject.
- [ ] Agent không tham gia việc nhóm vẫn dùng Playground như cũ; sau khi
  Coordination Run terminal, coordination guard được nhả. Nếu old managed Run
  vẫn giữ Agent `busy`, UI tiếp tục báo bận; chỉ enable gửi lại sau khi refresh
  thấy Agent `ready`.

## Graph scope

Không cần React Flow. Có thể render task cards theo topological level và hiển
thị dependency labels/arrows đơn giản. Mục tiêu là judge hiểu ordering, không
phải cung cấp graph editor.

## Event timeline

Hiển thị theo `sequence`, không chỉ timestamp:

```text
plan_requested
plan_validated
plan_failed / plan_timed_out
task_ready
attempt_started
attempt_timed_out
task_requeued
stale_result_rejected
attempt_cancelled / task_cancelled
task_completed
task_unblocked
coordination_completed
```

Event nên hiển thị task, attempt và Agent liên quan nếu có.
`EventTimeline` phải render được toàn bộ `CoordinationEventType` union trong
shared contract. Event chưa có presentation riêng phải dùng generic fallback
(`type + message`), không crash hoặc render rỗng; đặc biệt cover plan reject/fail,
dispatch reject/fail, task fail/skip/cancel, coordination fail/cancel và
`demo_fault_injected`.

Timeline chỉ sort theo `sequence` thật từ API; không hard-code rằng task A phải
complete trước/sau timeout của task B. Fixture UI nên có hai snapshot với hai
cách xen kẽ hợp lệ, và vẫn render được `stale_result_rejected` nếu event này nằm
sau retry hoặc trong khoảng poll ngắn sau event terminal. Nếu event tới sau cả
khoảng này, mở lại run từ list endpoint vẫn phải hiển thị được.

## Development không cần backend

Tạo một fixture snapshot local để code UI song song:

```text
planning
running với hai parallel tasks
retrying attempt 2
completed với final output
failed after max attempts
cancelled after user stop
```

Xóa hoặc cô lập fixture khỏi production path trước khi merge.

## Verification

- [ ] TypeScript typecheck pass.
- [ ] Production build pass.
- [ ] Existing single-Agent UI vẫn hoạt động.
- [ ] Reserved-Agent `409` giữ prompt và không tạo trạng thái chạy giả trên UI.
- [ ] Fake-timer test chứng minh event có sequence mới trong terminal grace
  window xuất hiện mà không cần reload.
- [ ] Cùng test chứng minh event mới không reset deadline 10 giây, polling dừng
  tại deadline, và response cũ sau switch/unmount không ghi đè run mới.
- [ ] Tách polling thành helper có timer/fetch được inject để test bằng Vitest
  trong môi trường Node, không bắt buộc thêm DOM test framework cho MVP.
- [ ] Khai báo trực tiếp `vitest` trong `apps/web` devDependencies, thêm
  `test: "vitest run"` cho web workspace, và đổi root `npm test` thành
  `npm run test --workspaces --if-present`; `npm run check` thật sự chạy polling
  test mới, không dựa vào dependency được hoist tình cờ từ server.
- [ ] Coordination UI không chứa scheduling logic.
- [ ] Empty/loading/error/terminal states đều dễ hiểu.
- [ ] Desktop hai cột graph/timeline.
- [ ] Mobile hoặc cửa sổ nhỏ vẫn sử dụng được theo một cột.

## Definition of Done

- Launch real Coordination Run qua API.
- Graph cập nhật khi task chuyển trạng thái.
- Retry luôn nhìn thấy được. Stale-result event nhìn thấy không cần reload nếu
  output cũ về trong lúc run/grace window; nếu về muộn hơn thì mở lại persisted
  run sẽ thấy. Fake-gateway test vẫn chứng minh stale rejection một cách xác định.
- Không cần reload thủ công trong demo.
- `npm run check` pass.

## Ngoài scope

- Drag-and-drop graph editor.
- WebSocket/SSE.
- Adaptive-plan editing.
- Frontend gọi nhiều Worker API để tự orchestrate.
