# Task 01 — Coordination Core và Scheduler

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-01-coordination-core`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

## Mục tiêu

Xây state machine trung tâm điều phối DAG. Module này nhận một plan đã validate,
quản lý task state, ready queue, giới hạn parallelism, capability matching và
mở khóa downstream task.

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
- [ ] Tạo task không dependency ở trạng thái `ready`.
- [ ] Tạo task có dependency ở trạng thái `blocked`.
- [ ] Tìm ready tasks theo thứ tự deterministic.
- [ ] Giới hạn tối đa hai task chạy song song.
- [ ] Không giao hai task đồng thời cho cùng một Agent.
- [ ] Chỉ chọn Agent `ready` có capability phù hợp.
- [ ] Nếu Agent vừa bị Playground chiếm, rollback dispatch và giữ task `ready`.
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
  capable Agent khi pool chỉ có một Agent.
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
  non-terminal run trên `DatabaseV2` được truyền vào; Task 05 gọi nó bên trong
  cùng store mutation của Agent lifecycle.
- [ ] `createRun()` atomically validate Agent eligibility/active-run conflict và
  persist run để serialize với lifecycle reservation.
- [ ] Public service methods throw existing `HttpError` với `404/409` semantics
  đúng contract; không throw plain Error cho expected domain conflicts.
- [ ] Gọi optional `CoordinationFaultPolicy` sau admission; core không hard-code
  tên demo mode hoặc task bị fault.
- [ ] Không gọi `AgentService` bên trong `JsonStore.mutate()`.

## Event tối thiểu

```text
coordination_created
plan_requested
plan_received
plan_validated
plan_rejected
plan_failed
plan_timed_out
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
- [ ] Non-busy admission failure/throw không để task hoặc Attempt bị kẹt.
- [ ] Timeout requeue tạo attempt ID mới.
- [ ] Retry ưu tiên capable Agent chưa chạy task đó.
- [ ] Late output của attempt cũ bị reject.
- [ ] Completion sau parent run cancelled bị reject.
- [ ] Attempt hiện hành completed được accept.
- [ ] Hết hai attempts tạo terminal failure.
- [ ] `maxParallelism = 2` được giữ.
- [ ] Final output lấy từ đúng final task.
- [ ] Permanent failure làm downstream skipped.
- [ ] Run failure cancel active sibling và reject completion đến sau đó.
- [ ] Một capable Worker vẫn retry được sau managed AgentRun failure.
- [ ] Stop atomically cancel unfinished tasks và late result không commit.
- [ ] Fault policy absent giữ production timeout; injected policy chỉ override
  attempt được chọn.
- [ ] Dependency output chứa quote/delimiter/instruction-looking text vẫn được
  serialize thành valid JSON data trong Worker prompt.
- [ ] Event sequence không trùng và đúng thứ tự.

Tests dùng fake Planner plan và fake Agent execution gateway; không gọi Ark thật.

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
