# Task 02 — Planner Service và DAG Validator

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-02-planner-dag-validator`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

## Mục tiêu

Biến user prompt thành một dependency graph có schema rõ ràng bằng Planner Agent,
sau đó coi output model là dữ liệu không tin cậy và validate hoàn toàn ở backend.

Planner được gọi qua Agent execution interface của Starter Kit. Không gọi ModelArk
SDK hoặc external AI service trực tiếp.

## Files sở hữu chính

```text
apps/server/src/planner-service.ts
apps/server/src/coordination-prompts.ts
apps/server/src/coordination-graph.ts
apps/server/src/coordination-graph.test.ts
apps/server/src/planner-service.test.ts
```

## Planner output contract

```json
{
  "version": 1,
  "summary": "Short plan summary",
  "tasks": [
    {
      "key": "research-a",
      "title": "Research approach A",
      "instruction": "Analyze benefits, risks and limitations.",
      "dependsOn": [],
      "requiredCapability": "research",
      "expectedOutput": "Concise analysis"
    },
    {
      "key": "synthesis",
      "title": "Produce recommendation",
      "instruction": "Compare the dependency results.",
      "dependsOn": ["research-a"],
      "requiredCapability": "synthesis",
      "expectedOutput": "Final recommendation"
    }
  ],
  "finalTaskKey": "synthesis"
}
```

Planner chỉ đề xuất graph. Planner không được quyết định Agent ID, attempt,
timeout, retry policy hoặc task status.

## Checklist implementation

- [ ] Build Planner prompt từ original user goal.
- [ ] Đưa allowed capabilities và `request.maxTasks` vào prompt (default policy
  hiện tại là 6; không hard-code trong validator).
- [ ] Yêu cầu JSON only, không Markdown.
- [ ] Strip một JSON Markdown fence nếu model vẫn trả fence.
- [ ] Parse bằng `JSON.parse`.
- [ ] Validate shape/length bằng Zod.
- [ ] Reject duplicate task key.
- [ ] Reject missing dependency.
- [ ] Reject self-dependency.
- [ ] Detect cycle bằng deterministic graph algorithm.
- [ ] Reject graph vượt quá `request.maxTasks`.
- [ ] Reject capability không nằm trong allowed capabilities.
- [ ] Reject capability không có worker nào đáp ứng.
- [ ] Validate `finalTaskKey` tồn tại.
- [ ] Bắt buộc reject nếu có task không nằm trên path dẫn tới final task.
- [ ] Không tự âm thầm sửa graph lỗi.
- [ ] Trả validation error đủ rõ để lưu vào event/UI nhưng không lộ secret.
- [ ] Planner admission/runtime failure trả typed failure để core emit
  `plan_failed`; Planner timeout trả typed failure để emit `plan_timed_out`.
- [ ] Dùng `request.timeoutMs` và best-effort cancel đúng Planner AgentRun khi
  timeout.
- [ ] Sau admission, await `request.registerAgentRun(run.id)`; nếu parent đã
  stop thì cancel Run và không parse/commit Planner output.
- [ ] Không retry Planner trong MVP.

## Planner service boundary

Implement đúng `PlannerService` trong shared contract và gọi đúng
`AgentExecutionGateway` của Task 03. Không tạo `PlannerExecutionGateway` riêng:

```ts
interface PlannerService {
  createPlan(request: PlannerRequest): Promise<PlannerResult>;
}
```

Tests inject fake `AgentExecutionGateway` trả discriminated
`AgentStartResult`; success handle hoàn tất bằng AgentRun có output string.

## Automated tests

- [ ] Valid DAG parse thành công.
- [ ] Markdown-fenced JSON được parse.
- [ ] Text không phải JSON bị reject.
- [ ] Duplicate key bị reject.
- [ ] Missing dependency bị reject.
- [ ] Self-dependency bị reject.
- [ ] Cycle hai node và nhiều node bị reject.
- [ ] Graph quá lớn bị reject.
- [ ] Orphan task không dẫn tới final task bị reject.
- [ ] Unknown capability bị reject.
- [ ] Missing final task bị reject.
- [ ] Planner failure không tạo task nửa chừng.
- [ ] Planner timeout không tạo task nửa chừng.
- [ ] Stop/admission race làm registration trả false và Planner Run bị cancel.
- [ ] Busy/not-configured Gateway result map thành typed `plan_failed`.

## Definition of Done

- Cùng một JSON input luôn cho cùng validation result.
- Planner output không thể bypass backend validator.
- Module không biết hoặc chọn Worker Agent ID.
- Có tests cho positive và negative cases.
- `npm run check` pass.

## Ngoài scope

- Plan repair bằng một AI call thứ hai.
- Adaptive replanning.
- Planner tự assign Agent.
- Dynamic model selection.
