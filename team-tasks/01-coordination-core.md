# Task 01 — Coordination Core và Scheduler

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-01-coordination-core`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

## Mục tiêu

Xây state machine trung tâm điều phối DAG. Module này nhận một plan đã validate,
gọi port của Task 03 để tạo General Workers, quản lý task state, ready queue,
giới hạn parallelism và mở khóa downstream task.

Module không gọi ModelArk trực tiếp. Mọi Planner/Worker Run phải đi qua interface
do Task 03 cung cấp.

## Files sở hữu chính

```text
apps/server/src/coordination-types.ts
apps/server/src/coordination-service.ts
apps/server/src/coordination-service.test.ts
```

Nếu cần sửa shared file ngoài danh sách này, trao đổi với leader trước để tránh
conflict.

`coordination-types.ts` đã được scaffold trên `main`; task này sở hữu việc giữ
nó đồng bộ với shared contract, không tạo file types thứ hai.

## Contract phải dùng

Import các khái niệm đã khóa trong `coordination-types.ts`:

```text
CoordinationRunStatus:
planning | running | completed | failed | cancelled

CoordinationTaskStatus:
blocked | ready | running | completed | failed | skipped | cancelled

TaskAttemptStatus:
dispatching | running | completed | failed | timed_out | cancelled | stale
```

Không redeclare một `CoordinationTask` rút gọn trong module riêng. Import type
đầy đủ từ `coordination-types.ts`; các field scheduler trực tiếp mutate gồm:

```ts
type SchedulerMutableTaskFields = Pick<
  CoordinationTask,
  | "status"
  | "attemptCount"
  | "currentAttemptId"
  | "assignedAgentId"
  | "output"
  | "error"
  | "startedAt"
  | "completedAt"
>;
```

## Checklist implementation

- [ ] Tạo Coordination Run ở trạng thái `planning`.
- [ ] Nhận validated plan từ Planner service.
- [ ] Cung cấp Planner `registerAgentRun` callback atomically persist Run ID chỉ
  khi parent còn `planning`, để stop/admission race cancel đúng Run.
- [ ] Chỉ apply PlannerResult nếu parent vẫn `planning`; late result sau stop
  không được tạo DAG hoặc đổi terminal status.
- [ ] Sau khi toàn bộ plan validate thành công, gọi `GeneralWorkerProvisioner`
  để tạo đúng `policy.maxParallelism` Worker mới (mặc định hai) cho run.
- [ ] Persist các Worker ID do backend tạo vào `run.workerAgentIds` và emit một
  `worker_created` cho mỗi Worker trước khi task đầu tiên được dispatch.
- [ ] Nếu tạo Worker lỗi hoặc kết quả không đủ/không unique/không `ready`, fail
  run với reason `worker_provision_failed`; không để task hoặc Attempt chạy nửa
  chừng.
- [ ] Sau provision, recheck parent vẫn `planning` trước khi attach Worker IDs và
  tạo DAG; nếu user đã Stop thì bỏ qua late result.
- [ ] Attach Worker IDs, tạo toàn bộ task và chuyển run sang `running` trong cùng
  một repository mutation.
- [ ] Khi khởi động lại, mọi run còn `planning` được atomically chuyển thành
  `failed`, emit `plan_failed` rồi `coordination_failed` với reason
  `server_restart_during_planning`, không gọi lại Planner, không tạo task và
  không còn giữ Planner hoặc Worker đã attach.
- [ ] Tạo task không dependency ở trạng thái `ready`.
- [ ] Tạo task có dependency ở trạng thái `blocked`.
- [ ] Tìm ready tasks theo thứ tự deterministic.
- [ ] Giới hạn tối đa hai task chạy song song.
- [ ] Không giao hai task đồng thời cho cùng một Agent.
- [ ] Chỉ chọn Agent `ready` nằm trong `run.workerAgentIds`; không phân loại role
  hoặc matching bằng tag.
- [ ] `createRun()` và Playground admission cùng serialize qua store mutation:
  bên reserve Agent trước thắng, bên còn lại nhận `409`.
- [ ] Gateway `busy` xóa provisional Attempt; không giữ hai Attempt cùng
  `attemptNumber`.
- [ ] Gateway failure khác/throw luôn cleanup reservation và fail rõ ràng; không
  để Attempt `dispatching` vô hạn.
- [ ] Khi task completed, mở khóa downstream nếu mọi dependency đã completed.
- [ ] Admission conflict không tăng `attemptCount` hoặc tiêu retry budget.
- [ ] Bắt đầu timeout chỉ sau khi AgentRun được admission thành công.
- [ ] Khi timeout, invalidate `currentAttemptId` trước khi requeue.
- [ ] Best-effort cancel old AgentRun nhưng không block retry vô hạn.
- [ ] Result chỉ được accept nếu parent run còn `running` và
  `attemptId === task.currentAttemptId`.
- [ ] Late completion emit `stale_result_rejected` và không ghi task output.
- [ ] `maxAttempts = 2`; không retry vô hạn.
- [ ] Runtime failure đưa task về ready nếu còn attempt; cho phép dùng lại cùng
  Worker nếu chưa có Worker khác rảnh.
- [ ] Worker failure atomically mark Attempt failed, clear reservation và emit
  `attempt_failed` trước khi requeue hoặc terminal failure.
- [ ] Reconciliation tick đánh thức ready task khi Agent rảnh trở lại.
- [ ] Khi task hết attempts, đánh dấu task `failed` và downstream `skipped`.
- [ ] Khi run fail, cancel/invalidate mọi active sibling trong cùng terminal
  mutation; terminal snapshot không còn task/Attempt `running`.
- [ ] Khi final task completed, lưu `finalOutput` và complete Coordination Run.
- [ ] Emit event có `sequence` tăng đơn điệu cho mọi transition quan trọng.
- [ ] `stopRun()` atomically cancel run/active attempts/unfinished tasks trước
  khi best-effort cancel AgentRuns ở ngoài mutation.
- [ ] Export standalone `CoordinationAgentGuard` implementation kiểm tra
  non-terminal run trên `DatabaseV2` được truyền vào; Task 05 gọi
  `assertMutable()` bên trong cùng store mutation của Agent
  lifecycle/Playground admission.
- [ ] `createRun()` atomically validate Planner/active-run conflict và persist
  run với `workerAgentIds: []`; frontend không được truyền Worker ID.
- [ ] Public service methods throw existing `HttpError` với `404/409` semantics
  đúng contract; không throw plain Error cho expected domain conflicts.
- [ ] Gọi optional `CoordinationFaultPolicy` sau admission; core không hard-code
  tên demo mode hoặc task bị fault.
- [ ] Khi fault policy trả decision, emit `attempt_started` rồi
  `demo_fault_injected` trong cùng mutation attach Attempt; chỉ arm timeout sau
  khi mutation commit.
- [ ] Catch/validate fault-policy result ở runtime; hook throw hoặc decision
  invalid phải fall back về timeout bình thường, không rollback attach mutation,
  không để Attempt `dispatching` hay AgentRun mồ côi.
- [ ] Không gọi `AgentService` bên trong `JsonStore.mutate()`.
- [ ] Không gọi `GeneralWorkerProvisioner` bên trong `JsonStore.mutate()`.

## Event tối thiểu

```text
coordination_created
plan_requested
plan_received
plan_validated
plan_rejected
plan_failed
plan_timed_out
worker_created
task_ready
attempt_dispatch_rejected
attempt_dispatch_failed
attempt_started
attempt_completed
attempt_failed
attempt_timed_out
attempt_cancelled
task_completed
task_requeued
stale_result_rejected
task_unblocked
task_failed
task_skipped
task_cancelled
coordination_completed
coordination_failed
coordination_cancelled
demo_fault_injected
```

## Automated tests

- [ ] Hai task độc lập được dispatch song song.
- [ ] Task có dependency chưa được dispatch sớm.
- [ ] Downstream chỉ ready khi tất cả dependency completed.
- [ ] Một Agent không nhận hai task cùng lúc.
- [ ] Busy Agent không làm scheduler crash.
- [ ] Admission conflict không tiêu retry budget.
- [ ] Admission conflict không để lại duplicate attempt number.
- [ ] Restart xóa provisional `dispatching` Attempt nên attempt number kế tiếp
  không bị trùng.
- [ ] Restart khi run còn `planning`, cả trường hợp chưa/có
  `plannerAgentRunId`, làm run fail; không dispatch Planner, không tạo task, có
  đúng một `plan_failed` và một `coordination_failed`, rồi create mới dùng lại
  đúng Planner thành công.
- [ ] Gọi `initialize()` lần hai không tạo thêm failure event; test giữ nguyên
  `plannerAgentRunId` và kiểm tra `completedAt`, safe `error`,
  `details.reason` đúng contract.
- [ ] Non-busy admission failure/throw không để task hoặc Attempt bị kẹt.
- [ ] Timeout requeue tạo attempt ID mới.
- [ ] Retry ưu tiên Worker chưa chạy task đó; nếu chưa có Worker khác rảnh thì
  task ở `ready` và reconciliation tick thử lại.
- [ ] Late output của attempt cũ bị reject.
- [ ] Completion sau parent run cancelled bị reject.
- [ ] Attempt hiện hành completed được accept.
- [ ] Hết hai attempts tạo terminal failure.
- [ ] `maxParallelism = 2` được giữ.
- [ ] Final output lấy từ đúng final task.
- [ ] Permanent failure làm downstream skipped.
- [ ] Mọi Worker của run đều `stopped`/`error`/missing làm run fail với
  `no_worker_available` thay vì chờ vô hạn.
- [ ] Run failure cancel active sibling và reject completion đến sau đó.
- [ ] Worker cũ vẫn có thể được dùng lại sau managed AgentRun failure nếu đã về
  `ready` và chưa có Worker khác rảnh.
- [ ] Plan hợp lệ tự tạo đúng hai General Workers ở default policy; user không
  cần tạo/chọn Worker hoặc cấu hình role trước.
- [ ] Provisioner failure không tạo task/Attempt nửa chừng; run kết thúc `failed`.
- [ ] Stop atomically cancel unfinished tasks và late result không commit.
- [ ] Fault policy absent giữ production timeout; injected policy chỉ override
  attempt được chọn.
- [ ] Fault policy throw, trả timeout âm/NaN hoặc sai shape đều fall back an toàn;
  admitted Attempt vẫn `running` với production timeout và không có demo event.
- [ ] Với attempt bị inject: `attempt_started < demo_fault_injected <
  attempt_timed_out < task_requeued < attempt_started` của retry.
- [ ] Dependency output chứa quote/delimiter/instruction-looking text vẫn được
  serialize thành valid JSON data trong Worker prompt.
- [ ] Event sequence không trùng; các quan hệ thứ tự trong §14 đúng nhưng test
  không ép task A hoàn thành trước/sau nhánh timeout song song của task B. Cover
  cả hai cách xen kẽ bằng fake gateway, không so sánh cứng toàn bộ event array.
- [ ] Trong run không bị truncate event history, sequence đúng liên tục
  `[1, 2, ..., N]`; test lọc theo `taskId`/`attemptId` để phân biệt task B với
  attempt B2.

Tests dùng fake Planner plan, fake `GeneralWorkerProvisioner` và fake Agent
execution gateway; không gọi Ark thật.

## Definition of Done

- Tất cả state transition nằm trong backend, không nằm ở UI.
- Core chạy end-to-end bằng fake gateway.
- Không có timer hoặc Promise bị bỏ quên sau test.
- Public methods và failure behavior được mô tả trong PR.
- `npm run check` pass.

## Ngoài scope

- Lease và heartbeat.
- Adaptive replanning.
- Evaluator Agent.
- Shared runtime workspace/artifacts giữa Worker Agents.
- Distributed scheduler.
