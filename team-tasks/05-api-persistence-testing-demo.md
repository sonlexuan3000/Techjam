# Task 05 — API, Persistence, Integration Tests và Demo

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-05-api-persistence-tests`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

## Mục tiêu

Nối các module MVP vào Fastify/JsonStore, cung cấp API cho frontend, persist
coordination state và xây end-to-end evidence có thể tái hiện khi chấm bài.

Task này không đưa scheduling logic vào route; route chỉ validate request và gọi
CoordinationService.
Expected `HttpError` từ Task 01 phải đi qua shared Fastify error handler để giữ
status `404/409`; route không catch rồi biến thành `500`.

## Files sở hữu chính

```text
apps/server/src/types.ts              # Database v2 composition only
apps/server/src/store.ts
apps/server/src/app.ts
apps/server/src/index.ts
apps/server/src/config.ts
apps/server/src/config.test.ts
apps/server/src/demo-fault-policy.ts
apps/server/src/agent-service.ts        # v2 lifecycle guard integration only
apps/server/src/app.test.ts
apps/server/src/coordination-integration.test.ts
README.md
docs/MULTI_AGENT_ARCHITECTURE.md
docs/DEMO.md
.env.example
```

## API tối thiểu

```text
POST /api/coordination-runs
GET  /api/coordination-runs
GET  /api/coordination-runs/:id
POST /api/coordination-runs/:id/stop
```

Create input:

```json
{
  "prompt": "Compare two approaches and recommend one",
  "plannerAgentId": "uuid"
}
```

Create trả HTTP `202` với Coordination Run trạng thái `planning`.
Stop trả HTTP `200` với full `StopCoordinationRunResponse`; không tự rút gọn DTO.

Task 05 chỉ wire `GeneralWorkerProvisioner` implementation của Task 03 vào
`CoordinationService`; route không tự tạo Worker và không nhận Worker config từ
frontend.

Detail response phải cung cấp một snapshot nhất quán:

```json
{
  "coordinationRun": {},
  "tasks": [],
  "attempts": [],
  "events": [],
  "latestSequence": 0
}
```

## Persistence

- [ ] Persist Coordination Runs.
- [ ] Persist Tasks.
- [ ] Persist Attempts.
- [ ] Persist Events.
- [ ] Có migration/normalization cho baseline database hiện tại.
- [ ] Browser refresh vẫn đọc được run.
- [ ] Server restart không để task giả ở trạng thái running.
- [ ] Server restart khi run còn `planning` atomically fail run với safe error,
  emit `plan_failed` rồi `coordination_failed` có reason
  `server_restart_during_planning` và giải phóng Agent.
- [ ] Event history có giới hạn; không lưu raw Codex stdout.
- [ ] Không lưu credential hoặc environment value.
- [ ] Inject Task 01 `CoordinationAgentGuard` vào AgentService.
- [ ] Inject Task 03 `GeneralWorkerProvisioner` vào CoordinationService.
- [ ] Sau Database v2 migration, update/start gọi guard trong store mutation;
  stop/delete reserve `stopped` trong guarded mutation trước cancel/archive.
- [ ] Public Playground admission gọi `assertMutable()` trong cùng mutation tạo
  Run/Message và chuyển Agent `ready → busy`; managed
  Planner/Worker admission không gọi guard này.
- [ ] Verify lifecycle reservation và Task 01 create reservation serialize trên
  cùng JsonStore; không duplicate một route-only pre-check.
- [ ] Trong `index.ts`, await theo đúng thứ tự: `AgentService.initialize()` →
  `CoordinationService.initialize()` → tạo/listen Fastify app; route không mở
  trước khi restart reconciliation hoàn tất.

## Controlled failure fixture

Live demo cần failure deterministic. Thêm development/demo-only fixture rõ ràng:

```text
timeout-first-worker-attempt
```

Yêu cầu:

- [ ] Chỉ hoạt động khi explicit demo config được bật.
- [ ] Parse đúng optional
  `COORDINATION_DEMO_FAULT=timeout-first-worker-attempt`; empty là off và giá trị
  lạ fail startup validation.
- [ ] Implement `CoordinationFaultPolicy`; không sửa scheduler internals hoặc tự
  invalidate Attempt trực tiếp từ route/test fixture.
- [ ] Return a safe decision/reason; Task 01 atomically emit
  `demo_fault_injected` khi policy trả decision khác `null`.
- [ ] Default run đã tự tạo hai General Workers và retry chọn Agent khác.
- [ ] Fixture có thể không cancel old Run để chứng minh late result bị reject.
- [ ] Không tạo hard-coded successful output.
- [ ] Retry Worker vẫn gọi real Agent qua Starter Kit.
- [ ] Có automated test với fake execution gateway; production không inject
  policy và giữ timeout mặc định.
- [ ] Fake fault policy throw hoặc trả decision invalid không làm Attempt kẹt
  `dispatching`, không bỏ mồ côi AgentRun và fall back về timeout bình thường.
- [ ] README nói rõ đây là controlled fixture được dùng để tái hiện recovery.

## Integration tests

- [ ] HTTP create Coordination Run trả `202`.
- [ ] Create trả trước khi Planner hoàn tất và trước khi Worker được tạo/chạy.
- [ ] Active Coordination Run thứ hai bị reject `409`.
- [ ] Invalid Planner Agent ID bị reject.
- [ ] Detail/stop unknown Coordination Run trả `404`, không rơi thành `500`.
- [ ] Planner không `ready` bị reject `409` khi create.
- [ ] Create body có field ngoài `{ prompt, plannerAgentId }` bị reject.
- [ ] Valid Planner output tạo persisted DAG.
- [ ] Sau plan validation, backend tạo đúng hai General Workers, persist hai ID
  unique vào run và emit hai `worker_created` events.
- [ ] Worker dùng đúng generic instruction; task title/instruction/dependency chỉ
  xuất hiện trong per-task message.
- [ ] Hai ready tasks chạy song song với fake gateway.
- [ ] Timeout requeue và tạo attempt 2.
- [ ] Old attempt completion tạo stale event.
- [ ] Controlled-timeout test assert thứ tự theo task/attempt ID:
  `started(B1) < fault(B1) < timed_out(B1) < requeued(B) < started(B2)`;
  không so sánh cứng vị trí `task_completed(A)` hoặc stale event trong toàn mảng.
- [ ] Cùng test assert `plan_validated < ready(A/B)`, cả `started(A1)` và
  `started(B1)` đứng trước event kết thúc đầu tiên, và cả hai task cha completed
  trước khi final task được mở khóa.
- [ ] Stop atomically cancel run/active attempts/unfinished tasks; late
  completion sau stop không commit.
- [ ] Final task unlock và complete run.
- [ ] Max attempts tạo failed run.
- [ ] Failed run không persist sibling task/Attempt ở trạng thái `running`.
- [ ] List/detail API trả dữ liệu đúng sau refresh/reinitialize.
- [ ] Restart trong lúc `planning`, trước hoặc sau khi lưu `plannerAgentRunId`,
  làm run fail, không tạo task, persist đúng hai failure events; create mới với
  cùng Agent không còn bị `409`.
- [ ] Reinitialize lần hai là idempotent: không nhân đôi failure event, giữ
  `plannerAgentRunId`, `completedAt`, safe `error` và reason.
- [ ] Existing `/api/agents` và Playground API tests vẫn pass với Agent không
  thuộc active Coordination Run.
- [ ] Playground message tới Planner hoặc auto-created Worker trong active run
  trả `409`, không tạo Message/AgentRun. Ít nhất một case dùng Worker vẫn `ready`
  để chứng minh coordination guard, không pass nhờ busy check cũ.
- [ ] Playground của Agent không tham gia run vẫn nhận `202`, và managed
  Planner/Worker của chính run vẫn start được.
- [ ] Race giữa Playground admission và `createRun()` chỉ cho đúng một bên
  reserve Planner; dùng barrier/fake để test riêng cả hai thứ tự commit. Playground
  thắng thì không có Coordination Run; create thắng thì không có Playground
  Message/AgentRun.
- [ ] Sau Coordination Run `completed | failed | cancelled`, coordination guard
  không còn reject. Test await fake managed completion/cleanup; khi Agent đã
  `ready` thì Playground nhận `202`. Nếu old Run còn giữ Agent `busy`, ordinary
  busy conflict vẫn đúng và không được hiểu nhầm là guard chưa nhả.
- [ ] Concurrent createRun với update/stop/delete không persist run tham chiếu
  Planner đã bị mutate/xóa.
- [ ] Non-busy Gateway admission failure không để Attempt `dispatching` sau
  request/tick.
- [ ] Với event history chưa bị truncate, `sequence` liên tục từ `1..N` và
  `latestSequence === events.at(-1)?.sequence`.

## Submission documentation

README cuối cùng cần có:

- Middleware problem và rationale.
- Provided Starter Kit versus team-added components.
- Architecture boundary.
- Required env: `ARK_API_KEY`, `ARK_MODEL`, optional `ARK_BASE_URL`.
- Optional non-secret demo flag `COORDINATION_DEMO_FAULT`; default/off behavior.
- One-command local startup.
- Planner setup cho demo; General Workers được backend tự tạo.
- Automated test command.
- Three-minute demo steps.
- Failure/recovery evidence.
- Event demo được giải thích theo quan hệ trước/sau giữa đúng task/attempt ID,
  không dùng danh sách số thứ tự toàn cục cố định; stale event có thể đến muộn.
- Known limitations.
- Không chứa secret hoặc screenshot có key.

Architecture page cần thể hiện:

```text
React UI
→ Fastify
→ CoordinationService
→ Planner/Graph Validator/Scheduler/Attempt Guard/Event Store
→ AgentService
→ AgentRunner
→ Codex CLI
→ ModelArk
```

## Three-minute demo acceptance

- [ ] Trước khi tạo Coordination Run, chạy một prompt ngắn trong existing
  single-Agent Playground để chứng minh Starter Kit baseline vẫn hoạt động.
- [ ] Chọn hoặc tạo Planner; không tạo/chọn Worker bằng tay.
- [ ] Gửi một goal thật từ UI.
- [ ] Planner thật đề xuất DAG.
- [ ] Hai tasks chạy song song.
- [ ] Một attempt timeout có kiểm soát.
- [ ] Task được requeue cho Agent khác.
- [ ] Old result bị reject nếu quay lại.
- [ ] Downstream task được unlock.
- [ ] Final output hiển thị.
- [ ] Event history chứng minh toàn bộ flow.
- [ ] UI cho thấy hai `worker_created` events và Worker IDs do backend cấp.
- [ ] Hai `attempt_started` đầu xuất hiện trước khi một trong hai nhánh kết thúc;
  final task chỉ mở khóa sau khi cả hai task cha completed. Không đọc demo theo
  một danh sách số thứ tự cố định giữa hai nhánh song song.
- [ ] Platform vẫn hiểu và điều khiển được sau failure.

Live ModelArk không bảo đảm old Run trả output trong đúng 10 giây terminal grace.
Nếu event stale về muộn hơn, mở lại persisted run để cho judge xem; automated
fake-gateway test là bằng chứng xác định rằng output cũ không thể commit.

## Definition of Done

- Fresh clone có setup instructions đủ để reviewer chạy.
- `npm run check` pass.
- Demo không cần sửa DB hoặc code bằng tay.
- Không có hidden manual step ngoài documented credentials/runtime setup.
- README ghi rõ General Worker records được giữ lại sau run trong MVP để audit;
  chưa có cleanup/reuse policy.
- Tất cả AI calls vẫn đi qua Starter Kit.

## Ngoài scope

- ECS/Terraform deployment.
- Production database/message broker.
- Hidden fallback DAG hoặc hard-coded model success.
- Full observability platform.
