# Task 01 — Coordination Core và Scheduler

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-01-coordination-core`
- **Reviewer:** `@sonlexuan3000`

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

## Contract phải khóa sớm

Định nghĩa và commit sớm các khái niệm dùng chung:

```text
CoordinationRunStatus:
planning | running | completed | failed | cancelled

CoordinationTaskStatus:
blocked | ready | running | completed | failed | skipped

AttemptStatus:
running | completed | failed | timed_out | stale
```

Task tối thiểu phải có:

```ts
{
  id: string;
  key: string;
  title: string;
  instruction: string;
  dependsOn: string[];
  requiredCapability: string;
  status: "blocked" | "ready" | "running" | "completed" | "failed" | "skipped";
  attemptCount: number;
  currentAttemptId: string | null;
  assignedAgentId: string | null;
  output: string | null;
  error: string | null;
}
```

## Checklist implementation

- [ ] Tạo Coordination Run ở trạng thái `planning`.
- [ ] Nhận validated plan từ Planner service.
- [ ] Tạo task không dependency ở trạng thái `ready`.
- [ ] Tạo task có dependency ở trạng thái `blocked`.
- [ ] Tìm ready tasks theo thứ tự deterministic.
- [ ] Giới hạn tối đa hai task chạy song song.
- [ ] Không giao hai task đồng thời cho cùng một Agent.
- [ ] Chỉ chọn Agent `ready` có capability phù hợp.
- [ ] Nếu Agent vừa bị Playground chiếm, rollback dispatch và giữ task `ready`.
- [ ] Khi task completed, mở khóa downstream nếu mọi dependency đã completed.
- [ ] Khi task hết attempts, đánh dấu task `failed` và downstream `skipped`.
- [ ] Khi final task completed, lưu `finalOutput` và complete Coordination Run.
- [ ] Emit event có `sequence` tăng đơn điệu cho mọi transition quan trọng.
- [ ] Không gọi `AgentService` bên trong `JsonStore.mutate()`.

## Event tối thiểu

```text
coordination_created
plan_requested
plan_validated
task_ready
attempt_started
task_completed
task_requeued
task_unblocked
task_failed
coordination_completed
coordination_failed
```

## Automated tests

- [ ] Hai task độc lập được dispatch song song.
- [ ] Task có dependency chưa được dispatch sớm.
- [ ] Downstream chỉ ready khi tất cả dependency completed.
- [ ] Một Agent không nhận hai task cùng lúc.
- [ ] Busy Agent không làm scheduler crash.
- [ ] `maxParallelism = 2` được giữ.
- [ ] Final output lấy từ đúng final task.
- [ ] Permanent failure làm downstream skipped.
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
- Shared files giữa Agents.
- Distributed scheduler.
